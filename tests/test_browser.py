import unittest
from note_automation.browser import save_note, metric, SafetyError


class Locator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector
    async def count(self):
        return int(self.selector != 'saved' or self.page.saved)
    async def is_visible(self):
        return True
    async def inner_text(self):
        return self.page.button if self.selector == 'button' else ''
    async def evaluate(self, script):
        return self.page.existing if self.selector == 'title' else ''
    async def fill(self, value):
        self.page.fills.append(self.selector)
    async def click(self):
        self.page.clicks.append(self.selector)
        self.page.saved = True
    async def wait_for(self, **kwargs):
        if not self.page.saved:
            raise TimeoutError()


class Page:
    def __init__(self, button='下書き保存', existing=''):
        self.button, self.existing = button, existing
        self.saved = False
        self.clicks, self.fills = [], []
    async def goto(self, url, **kwargs):
        self.url = url
    def locator(self, selector):
        return Locator(self, selector)


def config(url='https://editor.note.com/notes/new'):
    return {'new_draft_url': url, 'selectors': {'new_editor_marker': 'new', 'title_input': 'title', 'body_input': 'body', 'save_draft_button': 'button', 'saved_marker': 'saved'}}


class BrowserSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_missing_metric(self):
        self.assertIsNone(await metric(Page(button='-'), 'button'))
        self.assertEqual(await metric(Page(button='0'), 'button'), 0)
        self.assertEqual(await metric(Page(button='1,234'), 'button'), 1234)
        with self.assertRaises(ValueError):
            await metric(Page(button='約12'), 'button')
        with self.assertRaises(SafetyError):
            await metric(Page(), 'saved')

    async def test_publish_labels_never_clicked(self):
        for label in ['公開する', '投稿する', '公開設定', '下書き保存して公開する']:
            page = Page(button=label)
            with self.assertRaises(SafetyError):
                await save_note(page, config(), {'title': 'a', 'body': 'b'})
            self.assertEqual(page.clicks, [])
            self.assertEqual(page.fills, [])

    async def test_existing_article_never_edited(self):
        page = Page(existing='既存タイトル')
        with self.assertRaises(SafetyError):
            await save_note(page, config(), {'title': 'a', 'body': 'b'})
        self.assertEqual(page.fills, [])
        with self.assertRaises(SafetyError):
            await save_note(Page(), config('https://editor.note.com/notes/old/edit'), {})

    async def test_new_draft_single_save(self):
        page = Page()
        result = await save_note(page, config(), {'title': 'a', 'body': 'b'})
        self.assertEqual(result['status'], 'success')
        self.assertEqual(page.clicks, ['button'])
        self.assertEqual(page.fills, ['title', 'body'])

    async def test_missing_contract_stops(self):
        c = config()
        c['selectors']['title_input'] = ''
        page = Page()
        with self.assertRaises(SafetyError):
            await save_note(page, c, {})
        self.assertEqual(page.clicks, [])
