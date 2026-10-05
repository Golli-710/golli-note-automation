import argparse
import asyncio
import json
import os
from pathlib import Path
from .core import append_snapshot, compare, generate, save_draft, atomic_json, now
from .browser import collect, save_note


async def execute(args):
    auth = Path('.auth/storage_state.json')
    if args.command == 'login':
        from playwright.async_api import async_playwright
        auth.parent.mkdir(mode=0o700, exist_ok=True)
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto('https://note.com/login')
            await asyncio.to_thread(input, 'ブラウザでログイン完了後、Enterを押してください: ')
            await context.storage_state(path=str(auth))
            auth.chmod(0o600)
            await browser.close()
        return
    summary = {'started_at': now(), 'note_draft': {'status': 'not_attempted'}, 'human_review': ['実績の集計範囲', '本文の事実と実施済み施策', 'タイトル・タグ・サムネ', '公開は人間のみ']}
    try:
        from playwright.async_api import async_playwright
        config = json.loads(Path(args.config).read_text())
        if not auth.exists():
            raise RuntimeError('Login session missing; run login first')
        # Single-process lock prevents concurrent history writes and draft creation.
        Path('data').mkdir(exist_ok=True)
        lock = Path('data/run.lock')
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=not args.headed)
                context = await browser.new_context(storage_state=str(auth))
                page = await context.new_page()
                snapshot = await collect(page, config)
                history, added = append_snapshot('data/note_metrics.json', snapshot)
                current = history[-1]
                comparison = compare(current, history[-2] if len(history) > 1 else None)
                previous = json.loads(Path('data/editorial.json').read_text()) if Path('data/editorial.json').exists() else {}
                article = generate(current, comparison, previous.get('category'))
                draft = save_draft('drafts', current, article)
                summary.update(snapshot=current, comparison=comparison, analysis=article['reason'], theme=article['theme'], recommended_title=article['title'], hypothesis=article['hypothesis'], next_kpi=article['next_kpi'], markdown=str(draft), snapshot_added=added)
                if args.save_note:
                    summary['note_draft'] = {'status': 'attempting'}
                    # Never retry an uncertain save automatically.
                    attempt = Path('data/note-save-attempt.json')
                    if attempt.exists():
                        raise RuntimeError('Previous save attempt requires human review; inspect note drafts and clear attempt file manually')
                    atomic_json(attempt, {'snapshot_id': current['snapshot_id'], 'started_at': now()})
                    summary['note_draft'] = await save_note(page, config, article)
                    atomic_json(attempt, summary['note_draft'])
                atomic_json('data/editorial.json', {'category': article['category']})
                await browser.close()
        finally:
            os.close(fd)
            lock.unlink()
    except Exception as error:
        # Avoid raw Playwright logs, DOM dumps or credentials in summaries.
        summary['error'] = {'type': type(error).__name__, 'reason': str(error) if isinstance(error, (ValueError, RuntimeError)) and type(error).__module__ != 'playwright._impl._errors' else 'Browser operation failed; check selectors/session locally'}
        if summary['note_draft']['status'] == 'attempting':
            summary['note_draft']['status'] = 'failed_or_unconfirmed'
        raise
    finally:
        atomic_json('logs/summary.json', summary)
        report = '# note運営 実行summary\n\n```json\n' + json.dumps(summary, ensure_ascii=False, indent=2) + '\n```\n'
        Path('logs/summary.md').write_text(report)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
                f.write(report)
        print(report)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['login', 'run'])
    parser.add_argument('--config', default='config/local.json')
    parser.add_argument('--headed', action='store_true')
    parser.add_argument('--save-note', action='store_true')
    args = parser.parse_args()
    try:
        asyncio.run(execute(args))
    except Exception:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
