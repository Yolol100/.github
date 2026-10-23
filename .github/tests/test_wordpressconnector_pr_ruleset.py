import importlib.util
import json
from pathlib import Path
import unittest

src=Path(__file__).parents[1]/'scripts'/'apply-wordpressconnector-pr-ruleset.py'
spec=importlib.util.spec_from_file_location('wp_connector_ruleset',src)
rs=importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)
C={'schema_version':1,'repository':'Yolol100/wordpressconnector',
   'expected_main_sha':'c303ad2f3cdd8f878c196c77f79882b55bc2a70e',
   'required_check':'Required PR Gate','required_check_app_id':15368}

class Fake:
    def __init__(self):
        self.repo={'full_name':rs.TARGET,'visibility':'public','default_branch':'main','archived':False}
        self.branch={'protected':True,'commit':{'sha':C['expected_main_sha']}}
        self.rules=[{'id':24222354,'name':'Protect main','target':'branch',
                     'enforcement':'active','bypass_actors':[],
                     'conditions':{'ref_name':{'include':['~DEFAULT_BRANCH'],'exclude':[]}},
                     'rules':[{'type':'deletion'},{'type':'non_fast_forward'}]}]
        self.calls=[]
        self.fail_readback=False
        self.fail_create=False
    def __call__(self,args,input_text=None):
        self.calls.append((list(args),input_text))
        path=args[1];method=args[args.index('--method')+1] if '--method' in args else 'GET'
        if path=='repos/'+rs.TARGET:
            return json.dumps(self.repo)
        if path=='repos/'+rs.TARGET+'/branches/main':
            return json.dumps(self.branch)
        if path=='repos/'+rs.TARGET+'/rulesets':
            if method=='GET':return json.dumps([{'id':x['id'],'name':x['name']} for x in self.rules])
            if method=='POST':
                if self.fail_create:raise rs.ProtectionError('Simulated creation failure')
                x={'id':900, **json.loads(input_text)}
                self.rules.append(x)
                return json.dumps(x)
        if path.startswith('repos/'+rs.TARGET+'/rulesets/'):
            id=int(path.rsplit('/',1)[1])
            if method=='DELETE':
                self.rules=[x for x in self.rules if x['id']!=id]
                return ''
            for r in self.rules:
                if r['id']==id:
                    out=dict(r)
                    if id==900 and self.fail_readback:
                        out['enforcement']='disabled'
                    return json.dumps(out)
        raise AssertionError(f'Unexpected {method} {path}')

def writes(fake):return [x for x in fake.calls if '--method' in x[0] and x[0][x[0].index('--method')+1] in ('POST','DELETE')]

class Tests(unittest.TestCase):
    def test_positive_and_negative_rule_parameters(self):
        v=rs.desired(C)
        self.assertEqual({r['type'] for r in v['rules']}, {'pull_request','required_status_checks'})
        rules={r['type']:r.get('parameters') for r in v['rules']}
        self.assertTrue(rules['pull_request']['required_review_thread_resolution'])
        self.assertEqual(rules['pull_request']['required_approving_review_count'],0)
        self.assertEqual(rules['required_status_checks']['required_status_checks'], [{'context':'Required PR Gate','integration_id':15368}])
        self.assertEqual(v['bypass_actors'],[])
    def test_dry_run_does_not_write(self):
        f=Fake();p=rs.apply(C,dry_run=True,runner=f)
        self.assertEqual(p['preflight']['action'],'create');self.assertEqual(writes(f),[])
    def test_apply_create_and_readback(self):
        f=Fake();p=rs.apply(C,runner=f)
        self.assertEqual(p['created'],900)
        self.assertEqual(rs.inspect(C,runner=f)['action'],'no_change')
        self.assertEqual([x['id'] for x in f.rules],[24222354,900])
    def test_repeat_is_no_change(self):
        f=Fake();rs.apply(C,runner=f);before=len(writes(f))
        self.assertEqual(rs.apply(C,runner=f)['preflight']['action'],'no_change')
        self.assertEqual(len(writes(f)),before)
    def test_private_drift_fails_before_writes(self):
        f=Fake();f.repo['visibility']='private'
        with self.assertRaises(rs.ProtectionError):rs.apply(C,runner=f)
        self.assertEqual(writes(f),[])
    def test_unprotected_base_fails_before_writes(self):
        f=Fake();f.rules[0]['rules']=[{'type':'deletion'}]
        with self.assertRaises(rs.ProtectionError):rs.apply(C,runner=f)
        self.assertEqual(writes(f),[])
    def test_main_changed_fails_before_writes(self):
        f=Fake();f.branch['commit']['sha']='a'*40
        with self.assertRaises(rs.ProtectionError):rs.apply(C,runner=f)
        self.assertEqual(writes(f),[])
    def test_existing_unexpected_ruleset_fails_closed(self):
        f=Fake();f.rules.append({'id':901,**rs.desired(C)})
        f.rules[-1]['rules'][0]['parameters']['required_approving_review_count']=1
        with self.assertRaises(rs.ProtectionError):rs.apply(C,runner=f)
        self.assertEqual(writes(f),[])
    def test_failed_creation_does_not_modify_base(self):
        f=Fake();f.fail_create=True
        with self.assertRaises(rs.ProtectionError):rs.apply(C,runner=f)
        self.assertEqual([x['id'] for x in f.rules],[24222354])
    def test_mismatched_readback_rolls_back_only_new_rule(self):
        f=Fake();f.fail_readback=True
        with self.assertRaises(rs.ProtectionError):rs.apply(C,runner=f)
        self.assertEqual([x['id'] for x in f.rules],[24222354])
    def test_server_added_optional_defaults_are_semantically_equal(self):
        r=rs.desired(C)
        r['rules'][0]['parameters']['required_reviewers']=[]
        del r['rules'][0]['parameters']['allowed_merge_methods']
        del r['rules'][1]['parameters']['do_not_enforce_on_create']
        self.assertTrue(rs.policy_matches(r,C))
    def test_missing_required_check_app_fails_closed(self):
        r=rs.desired(C)
        del r['rules'][1]['parameters']['required_status_checks'][0]['integration_id']
        self.assertFalse(rs.policy_matches(r,C))
    def test_missing_conversation_resolution_fails_closed(self):
        r=rs.desired(C)
        r['rules'][0]['parameters']['required_review_thread_resolution']=False
        self.assertFalse(rs.policy_matches(r,C))

    def test_unexpected_config_fails_closed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'config.json';p.write_text(json.dumps({**C,'repository':'Yolol100/Orchestrator'}))
            with self.assertRaises(rs.ProtectionError):rs.read_config(p)

if __name__=='__main__':unittest.main()