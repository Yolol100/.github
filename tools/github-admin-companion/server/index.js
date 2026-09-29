import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';

const execFileAsync = promisify(execFile);

function assertRepo(repo) {
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo)) {
    throw new Error('repo must be in owner/name form');
  }
}

async function gh(args) {
  try {
    const { stdout, stderr } = await execFileAsync('gh', args, {
      windowsHide: true,
      maxBuffer: 2 * 1024 * 1024,
      env: process.env
    });
    if (stderr?.trim()) process.stderr.write(stderr);
    return stdout.trim();
  } catch (error) {
    const details = error?.stderr || error?.stdout || error?.message || String(error);
    throw new Error(`gh command failed: ${String(details).trim()}`);
  }
}

async function authStatus() {
  await gh(['auth', 'status', '--hostname', 'github.com']);
  return true;
}

async function getRepoAbout(repo) {
  assertRepo(repo);
  await authStatus();
  const raw = await gh(['repo', 'view', repo, '--json', 'nameWithOwner,description,homepageUrl,repositoryTopics,url']);
  return JSON.parse(raw);
}

async function setRepoAbout(repo, description, homepage, topics) {
  assertRepo(repo);
  await authStatus();

  const current = await getRepoAbout(repo);
  const currentTopics = (current.repositoryTopics || []).map((x) => x.name).sort();
  const desiredTopics = [...new Set((topics || []).map((x) => x.trim().toLowerCase()).filter(Boolean))].sort();

  const args = ['repo', 'edit', repo, '--description', description, '--homepage', homepage];

  for (const topic of currentTopics) {
    if (!desiredTopics.includes(topic)) args.push('--remove-topic', topic);
  }
  for (const topic of desiredTopics) {
    if (!currentTopics.includes(topic)) args.push('--add-topic', topic);
  }

  await gh(args);
  return getRepoAbout(repo);
}

async function getPins(login) {
  await authStatus();
  const query = `query($login:String!){user(login:$login){login viewerCanChangePinnedItems pinnedItems(first:6,types:[REPOSITORY]){nodes{... on Repository{nameWithOwner url}}} pinnedItemsRemaining}}`;
  const raw = await gh(['api', 'graphql', '-f', `query=${query}`, '-F', `login=${login}`]);
  return JSON.parse(raw);
}

const server = new McpServer({ name: 'github-admin-companion', version: '0.1.0' });

server.tool(
  'github_auth_status',
  'Verify that the local GitHub CLI is authenticated to github.com.',
  {},
  async () => {
    await authStatus();
    return { content: [{ type: 'text', text: 'GitHub CLI authentication is valid.' }] };
  }
);

server.tool(
  'github_repo_get_about',
  'Read a repository description, homepage URL and topics from GitHub.',
  { repo: z.string().describe('Repository in owner/name form') },
  async ({ repo }) => {
    const result = await getRepoAbout(repo);
    return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
  }
);

server.tool(
  'github_repo_set_about',
  'Set repository description, homepage URL and the exact topic set, then read back the result.',
  {
    repo: z.string().describe('Repository in owner/name form'),
    description: z.string().max(350),
    homepage: z.string().url(),
    topics: z.array(z.string().regex(/^[a-z0-9-]{1,50}$/)).max(20)
  },
  async ({ repo, description, homepage, topics }) => {
    const result = await setRepoAbout(repo, description, homepage, topics);
    return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
  }
);

server.tool(
  'github_profile_get_pins',
  'Read the current repository pins for a GitHub user profile and whether the authenticated viewer may change them.',
  { login: z.string().regex(/^[A-Za-z0-9-]{1,39}$/) },
  async ({ login }) => {
    const result = await getPins(login);
    return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
  }
);

server.tool(
  'github_profile_pin_limitations',
  'Explain the current GitHub API limitation for changing personal profile pins programmatically.',
  {},
  async () => ({
    content: [{
      type: 'text',
      text: 'GitHub exposes personal profile pins for reading through GraphQL, but does not expose a supported public API mutation to change them. Use GitHub profile > Customize your pins for writes; this plugin intentionally does not automate undocumented web internals.'
    }]
  })
);

const transport = new StdioServerTransport();
await server.connect(transport);
