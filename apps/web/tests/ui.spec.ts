import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/** End-to-end checks against a running app.
 *
 * These exist because the API test suite could not see the bug that mattered most: every
 * wikilink inside a note rendered as `<a href="" target="_blank">`, so clicking one opened a
 * new tab showing the page you were already on. Only a real browser catches that.
 *
 * BASE_URL, WIKI_EMAIL and WIKI_PASSWORD select the target; defaults hit a local server.
 */
const BASE = process.env.BASE_URL || 'http://localhost:8899';
const EMAIL = process.env.WIKI_EMAIL || 'admin@example.com';
const PASSWORD = process.env.WIKI_PASSWORD || 'dev';

/** A bearer token, for tests that need to ask the API something directly. */
async function tokenFor(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${BASE}/api/auth/login`, {
    data: { email: EMAIL, password: PASSWORD },
  });
  return (await res.json()).access_token;
}

async function login(page: Page) {
  await page.goto(`${BASE}/login`);
  await page.getByLabel('Email').fill(EMAIL);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByRole('button', { name: /log in/i }).click();
  await expect(page).toHaveURL(new RegExp(`${BASE.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/?$`));
}

test.describe('wiki navigation', () => {
  test.beforeEach(async ({ page }) => login(page));

  test('every wikilink on the index navigates in the same tab to a distinct page', async ({
    page,
    context,
  }) => {
    await page.goto(`${BASE}/doc/index`);
    const links = page.locator('.markdown-body a[href^="/doc/"]');
    // The body arrives from an async fetch, so wait for it rather than racing the render.
    await expect(links.first()).toBeVisible();
    const count = await links.count();
    // Not a size assertion: CI runs against a small fixture wiki, a real one has hundreds.
    expect(count).toBeGreaterThan(2);

    // No link may be an empty href, and none may open a new tab.
    for (let i = 0; i < count; i++) {
      const href = await links.nth(i).getAttribute('href');
      expect(href, `link ${i} has no destination`).toBeTruthy();
      expect(href).toMatch(/^\/doc\/.+/);
      expect(await links.nth(i).getAttribute('target')).toBeNull();
    }

    // Click through the first several and confirm each lands somewhere different.
    const seen = new Set<string>();
    for (let i = 0; i < Math.min(count, 6); i++) {
      await page.goto(`${BASE}/doc/index`);
      await expect(page.locator('.markdown-body a[href^="/doc/"]').first()).toBeVisible();
      const target = await page.locator('.markdown-body a[href^="/doc/"]').nth(i).getAttribute('href');
      const before = context.pages().length;
      await page.locator('.markdown-body a[href^="/doc/"]').nth(i).click();
      await expect(page).toHaveURL(`${BASE}${target}`);
      expect(context.pages().length, 'a new tab was opened').toBe(before);
      await expect(page.locator('.markdown-body h1, article h1').first()).toBeVisible();
      seen.add(page.url());
    }
    expect(seen.size, 'different links landed on the same page').toBeGreaterThan(1);
  });

  test('cmd+click opens a wikilink in a new tab', async ({ page, context }) => {
    await page.goto(`${BASE}/doc/index`);
    const link = page.locator('.markdown-body a[href^="/doc/"]').first();
    await expect(link).toBeVisible();
    const href = await link.getAttribute('href');

    const [newPage] = await Promise.all([
      context.waitForEvent('page'),
      link.click({ modifiers: [process.platform === 'darwin' ? 'Meta' : 'Control'] }),
    ]);
    // A new tab starts at about:blank and navigates a moment later, which is visible over a
    // real network even though it is instant locally.
    await newPage.waitForURL(`${BASE}${href}`, { timeout: 15_000 });
    // The original tab stays where it was.
    expect(page.url()).toBe(`${BASE}/doc/index`);
  });

  test('external links open in a new tab', async ({ page }) => {
    await page.goto(`${BASE}/doc/src-attention-is-all-you-need`);
    const external = page.locator('.markdown-body a[target="_blank"]').first();
    if ((await external.count()) > 0) {
      expect(await external.getAttribute('href')).toMatch(/^https?:\/\//);
    }
  });

  test('scroll resets when following a link', async ({ page }) => {
    await page.goto(`${BASE}/doc/index`);
    await expect(page.locator('.markdown-body a[href^="/doc/"]').first()).toBeVisible();
    // Only meaningful on a page tall enough to scroll; CI's fixture wiki is not.
    const scrollable = await page.evaluate(
      () => document.documentElement.scrollHeight > window.innerHeight + 200,
    );
    test.skip(!scrollable, "this wiki's index is too short to scroll");
    await page.evaluate(() => window.scrollTo(0, 600));
    expect(await page.evaluate(() => window.scrollY)).toBeGreaterThan(100);
    await page.locator('.markdown-body a[href^="/doc/"]').first().click();
    await page.waitForTimeout(300);
    expect(await page.evaluate(() => window.scrollY)).toBeLessThan(50);
  });

  test('a source cannot be edited and shows its literature note', async ({ page }) => {
    await page.goto(`${BASE}/doc/src-attention-is-all-you-need`);
    await expect(page.getByText('captured source')).toBeVisible();
    await expect(page.getByRole('link', { name: /edit/i })).toHaveCount(0);
  });

  test('search finds a note and opens it', async ({ page }) => {
    await page.goto(BASE);
    await page.getByLabel(/search your knowledge base/i).fill('attention');
    await expect(page.locator('.result-item').first()).toBeVisible({ timeout: 10_000 });
    await page.locator('.result-item').first().click();
    await expect(page).toHaveURL(/\/doc\//);
  });
});

test.describe('appearance', () => {
  test.beforeEach(async ({ page }) => login(page));

  test('theme toggle switches between light and dark', async ({ page }) => {
    await page.goto(`${BASE}/doc/index`);
    const toggle = page.locator('button.icon-button');
    const themeOf = () => page.evaluate(() => document.documentElement.getAttribute('data-theme'));

    await toggle.click();
    expect(await themeOf()).toBe('light');
    await toggle.click();
    expect(await themeOf()).toBe('dark');

    // Survives a reload.
    await page.reload();
    expect(await themeOf()).toBe('dark');
  });

  test('long notes get a table of contents', async ({ page }) => {
    await page.goto(`${BASE}/doc/index`);
    await expect(page.locator('.toc')).toBeVisible();
    await page.locator('.toc a').first().click();
    await page.waitForTimeout(400);
  });
});

test.describe('ask ai', () => {
  test.beforeEach(async ({ page }) => login(page));

  test('citations appear long before the answer finishes', async ({ page, request }) => {
    const res = await request.get(`${BASE}/api/llm/models`, {
      headers: { Authorization: `Bearer ${await tokenFor(request)}` },
    });
    // The route answers 200 without a key; what matters is whether it settled on a model.
    const status = res.ok() ? await res.json() : null;
    test.skip(!status?.will_use, 'no LLM configured, so there is no answer to stream');
    test.setTimeout(180_000);
    await page.goto(`${BASE}/ask`);
    await page.getByLabel('Your question').fill('What is attention?');
    const started = Date.now();
    await page.getByRole('button', { name: 'Ask' }).click();

    await expect(page.locator('.citations-inline').first()).toBeVisible({ timeout: 20_000 });
    const citationsAt = Date.now() - started;
    await expect(page.locator('.ask-answer .markdown-body').first()).toBeVisible({
      timeout: 90_000,
    });
    const firstTextAt = Date.now() - started;

    // Sources should be on screen almost immediately — that is the point of streaming.
    expect(citationsAt).toBeLessThan(8_000);
    console.log(`citations ${citationsAt}ms, first answer text ${firstTextAt}ms`);
  });
});

test.describe('finding your way in', () => {
  test.beforeEach(async ({ page }) => login(page));

  test('the home page offers hubs and a random note before you type', async ({ page }) => {
    await page.goto(BASE);

    // Maps of content are the curated way in; a bare search box only helps if you already
    // know what to search for.
    await expect(page.getByRole('heading', { name: 'Start here' })).toBeVisible();
    const hubs = page.locator('.hub-card');
    await expect(hubs.first()).toBeVisible();
    expect(await hubs.count()).toBeGreaterThan(0);

    const random = page.locator('.random-card');
    await expect(random).toBeVisible();
    const first = await random.locator('.random-title').innerText();

    // "Another" must actually fetch a different note, not re-render the same one.
    let changed = false;
    for (let i = 0; i < 6 && !changed; i++) {
      await page.getByRole('button', { name: /another/i }).click();
      await expect(random).toBeVisible();
      changed = (await random.locator('.random-title').innerText()) !== first;
    }
    expect(changed, 'refreshing never produced a different note').toBe(true);

    // Clicking a hub opens it in the same tab.
    await hubs.first().click();
    await expect(page).toHaveURL(/\/doc\//);
  });

  test('a note draws its own neighbourhood, and the map opens on demand', async ({ page }) => {
    // Discovered rather than hardcoded: the suite must run against any wiki, including a
    // freshly built image in CI that holds only the test fixture.
    await page.goto(`${BASE}/doc/index`);
    const first = page.locator('.markdown-body a[href^="/doc/"]').first();
    await expect(first).toBeVisible();
    await first.click();
    await expect(page).toHaveURL(/\/doc\//);

    const panel = page.locator('.connections');
    await expect(panel).toBeVisible();
    // Collapsed by default: vis-network is ~600KB and most readers only want the note.
    await expect(panel.locator('canvas')).toHaveCount(0);

    await panel.getByRole('button', { name: /show map/i }).click();
    await expect(panel.locator('canvas')).toBeVisible({ timeout: 20000 });

    // The hop toggle is what makes it a neighbourhood rather than an atlas.
    await expect(panel.getByRole('button', { name: '2 hops' })).toBeVisible();
    await panel.getByRole('button', { name: '2 hops' }).click();
    await expect(panel.locator('canvas')).toBeVisible({ timeout: 20000 });
  });

  test('the global graph page is gone', async ({ page }) => {
    await page.goto(`${BASE}/graph`);
    // The SPA catch-all renders Not found rather than a hairball.
    await expect(page.locator('canvas')).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'Graph', exact: true })).toHaveCount(0);
  });

  test('browse leads with maps of content, not a wall of tags', async ({ page }) => {
    await page.goto(`${BASE}/browse`);
    const maps = page.getByRole('heading', { name: 'Maps of content' });
    const tags = page.getByRole('heading', { name: 'Tags', exact: true });
    await expect(maps).toBeVisible();
    await expect(tags).toBeVisible();

    // Order matters: hubs must come before tags on the page.
    const mapsY = (await maps.boundingBox())!.y;
    const tagsY = (await tags.boundingBox())!.y;
    expect(mapsY).toBeLessThan(tagsY);
  });
});
