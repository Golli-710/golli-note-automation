"""Only rendered DOM operations; never calls note endpoints directly."""
from urllib.parse import urlparse
from .core import METRICS, now, number


class SafetyError(RuntimeError):
    pass


def note_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('note.com', 'editor.note.com') or parsed.username or parsed.password:
        raise SafetyError('Unexpected note origin')
    return url


async def unique(root, selector):
    if not selector:
        raise SafetyError('Required DOM selector is not configured')
    loc = root.locator(selector)
    if await loc.count() != 1 or not await loc.is_visible():
        raise SafetyError('Required DOM element missing, ambiguous, or hidden')
    return loc


async def text(root, selector):
    value = (await (await unique(root, selector)).inner_text()).strip()
    if not value:
        raise SafetyError('Empty required DOM text')
    return value


async def metric(root, selector):
    if not selector:
        return None
    value = await text(root, selector)
    return None if value == '-' else number(value)


async def collect(page, config):
    s = config['selectors']
    await page.goto(note_url(config['dashboard_url']), wait_until='domcontentloaded')
    note_url(page.url)
    if not s['dashboard_marker']:
        raise SafetyError('Dashboard marker not configured')
    await page.locator(s['dashboard_marker']).wait_for(state='visible', timeout=15000)
    await unique(page, s['dashboard_marker'])
    if s.get('ready_marker'):
        await page.locator(s['ready_marker']).wait_for(state='visible', timeout=15000)
        await unique(page, s['ready_marker'])
    aggregated_at = await text(page, s['aggregated_at']) if s.get('aggregated_at') else None
    period = await text(page, s['period'])
    period_key = await text(page, s['period_key'])
    totals = {k: await metric(page, s['totals'].get(k)) for k in METRICS}
    if not any(v is not None for v in totals.values()):
        raise SafetyError('No observable totals')
    container = await unique(page, s['articles_container'])
    if not s['article_rows']:
        raise SafetyError('Article row selector missing')
    if s.get('article_headers'):
        actual = [(await cell.inner_text()).strip() for cell in await container.locator('thead th').all()]
        if actual != s['article_headers']:
            raise SafetyError('Article column headers changed')
    rows = container.locator(s['article_rows'])
    if await rows.count() == 0:
        raise SafetyError('No article rows; cannot distinguish empty data from DOM change')
    articles = []
    for i in range(await rows.count()):
        row = rows.nth(i)
        link = await unique(row, s['article_link'])
        href = await link.get_attribute('href')
        from urllib.parse import urljoin
        url = note_url(urljoin(page.url, href or ''))
        if '/n/' not in urlparse(url).path:
            raise SafetyError('Article identity missing')
        articles.append(dict(id=url, title=await text(row, s['article_title']), published_at=await text(row, s['article_date']) if s.get('article_date') else None, **{k: await metric(row, s['article_metrics'].get(k)) for k in METRICS}))
    if len({a['id'] for a in articles}) != len(articles):
        raise SafetyError('Duplicate article identities')
    if s.get('aggregated_at') and await text(page, s['aggregated_at']) != aggregated_at:
        raise SafetyError('Aggregation changed during collection')
    return {'collected_at': now(), 'period': period, 'period_key': period_key, 'source': 'note_rendered_dom', 'source_aggregated_at': aggregated_at, 'totals': totals, 'articles': articles, 'referrers': await text(page, s['referrers']) if s.get('referrers') else None}


async def save_note(page, config, article):
    s = config['selectors']
    url = note_url(config['new_draft_url'])
    if urlparse(url).path.rstrip('/') != '/notes/new':
        raise SafetyError('Only a new draft editor may be opened')
    await page.goto(url, wait_until='domcontentloaded')
    note_url(page.url)
    # The configured marker MUST positively identify an empty new editor.
    await unique(page, s['new_editor_marker'])
    title = await unique(page, s['title_input'])
    body = await unique(page, s['body_input'])
    async def content(loc):
        return await loc.evaluate('(el) => el.value === undefined ? el.innerText : el.value')
    if (await content(title)).strip() or (await content(body)).strip():
        raise SafetyError('Refusing to edit a nonempty editor')
    button = await unique(page, s['save_draft_button'])
    if (await button.inner_text()).strip() != '下書き保存':
        raise SafetyError('Only exact 下書き保存 is allowed')
    if not s.get('saved_marker'):
        raise SafetyError('Saved marker not configured')
    if await page.locator(s['saved_marker']).count():
        raise SafetyError('Saved marker must not exist before saving')
    await title.fill(article['title'])
    await body.fill(article['body'])
    # Tags are entered only if a draft-only tag field has been verified.
    if s.get('tags_input'):
        await (await unique(page, s['tags_input'])).fill(' '.join('#' + t for t in article['tags']))
    # Revalidate immediately before the sole click in the implementation.
    button = await unique(page, s['save_draft_button'])
    if (await button.inner_text()).strip() != '下書き保存':
        raise SafetyError('Draft save action changed')
    await button.click()
    await page.locator(s['saved_marker']).wait_for(state='visible', timeout=15000)
    await unique(page, s['saved_marker'])
    return {'status': 'success', 'url': note_url(page.url)}
