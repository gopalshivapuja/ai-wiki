import { expect, test, type Page } from '@playwright/test';

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
    expect(count).toBeGreaterThan(8);

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

  test('citations appear long before the answer finishes', async ({ page }) => {
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
