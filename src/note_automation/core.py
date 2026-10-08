"""Pure data pipeline. Missing values stay missing; no fabricated observations."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

METRICS = ('impressions', 'page_views', 'likes', 'comments', 'sales_yen')


def now():
    return datetime.now(timezone.utc).isoformat()


def number(text):
    value = text.strip().replace(',', '')
    if not re.fullmatch(r'(?:¥|￥)?\d+(?:円)?', value):
        raise ValueError('Metric is not an unambiguous nonnegative integer')
    return int(re.sub(r'[^0-9]', '', value))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)


def append_snapshot(path, snapshot):
    path = Path(path)
    history = json.loads(path.read_text()) if path.exists() else []
    if not isinstance(history, list):
        raise ValueError('History must be a list')
    if snapshot.get('source_aggregated_at'):
        for existing in history:
            if all(existing.get(k) == snapshot.get(k) for k in ('source', 'source_aggregated_at', 'period', 'period_key')):
                fields = ('totals', 'articles', 'referrers')
                if any(existing.get(k) != snapshot.get(k) for k in fields):
                    raise ValueError('Conflicting values for the same source aggregation time')
                return history, False
    digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if any(s['collected_at'] == snapshot['collected_at'] for s in history):
        if any({k: v for k, v in s.items() if k != 'snapshot_id'} == snapshot for s in history):
            return history, False
        raise ValueError('Conflicting snapshot at same collection time')
    snapshot = dict(snapshot, snapshot_id=digest)
    history.append(snapshot)
    history.sort(key=lambda s: s['collected_at'])
    atomic_json(path, history)
    return history, True


def delta(current, previous):
    return {k: current.get(k) - previous.get(k) if current.get(k) is not None and previous.get(k) is not None else None for k in METRICS}


def compare(current, previous):
    comparable = previous is not None and current['period_key'] == previous['period_key'] and current['period'] == previous['period']
    old = {a['id']: a for a in previous['articles']} if comparable else {}
    totals = current['totals']
    def ratio(a, b):
        return totals[a] / totals[b] if totals.get(a) is not None and totals.get(b) else None
    return {
        'comparable': comparable,
        'reason': None if comparable else '初回、または集計範囲が異なるため増減は算出しない',
        'totals_delta': delta(totals, previous['totals']) if comparable else dict.fromkeys(METRICS),
        'articles_delta': {a['id']: delta(a, old[a['id']]) if a['id'] in old else dict.fromkeys(METRICS) for a in current['articles']},
        'pv_per_impression_reference': ratio('page_views', 'impressions'),
        'likes_per_pv': ratio('likes', 'page_views'),
        'ratio_caveat': 'PV / impressionsは参考比率。集計対象や外部流入が異なるため厳密なCTRではない。'
    }


def generate(snapshot, comparison, previous_category=None):
    """Auditable deterministic editorial decisions, swappable generator boundary."""
    totals = snapshot['totals']
    gain = comparison['totals_delta'].get('page_views')
    category = 'A' if previous_category != 'A' else 'D'
    if gain is not None and gain <= 0:
        category = 'B'
    if all(v is None for v in totals.values()):
        category = 'C'
    themes = {'A': '運営結果から次の一手を決める', 'B': '次の記事で導入文を試す', 'C': 'AI副業実験の計測を整える', 'D': '実績の読み方と記録方法を共有する'}
    labels = {'impressions': 'インプレッション', 'page_views': 'PV', 'likes': 'スキ', 'comments': 'コメント', 'sales_yen': '売上（円）'}
    facts = '\n'.join(f'- {labels[k]}：{v}' for k, v in totals.items() if v is not None)
    changes = '\n'.join(f'- {labels[k]}の前回差：{v:+d}' for k, v in comparison['totals_delta'].items() if v is not None)
    article_facts = '\n'.join(f'- {a["title"]}：' + '、'.join(f'{labels[k]} {a[k]}' for k in METRICS if a.get(k) is not None) for a in snapshot['articles'])
    titles = [f'ChatGPTにnoteを任せた。{themes[category]}', '月10万円を目指すnote実験、いま確認できた数字', '伸びたと言う前に、noteの実績を開いてみた', 'AIに次の一手を聞く。その前に運営データを渡した', 'note運営をAIに任せる実験で、次に確かめたいこと']
    hypothesis = '次の記事の導入で読者が得られる具体的な内容を示すと、同じ集計範囲のPVとスキに変化が出るか。因果関係は断定しない。'
    body = f'''月10万円を目指して、note運営をChatGPTに任せる実験を続けています。

今回は、数字を見てから次に書く内容を決めました。目標に届いたかどうかと、記事が読まれたかどうかは分けて考えます。

## 今回確認できたこと

集計範囲：{snapshot['period']}
取得日時：{snapshot['collected_at']}

{facts}

### 記事ごとの記録

{article_facts}

## 前回との違い

{changes or comparison['reason'] or '比較できる数値がありません。'}

{comparison['ratio_caveat']}

## AIが選んだ次の一手

{themes[category]}。

まだ実施結果のない施策を、成功例としては書けません。次の記事では冒頭に「何を試し、何が分かるのか」を置く案を検討します。

## 次に確かめること

{hypothesis}

次回は同じ集計範囲でPV、スキ、コメント、売上を確認します。取得できない項目は未確認のまま残します。公開前に人間が内容と実際の施策を確認します。
'''
    return {'category': category, 'theme': themes[category], 'title_candidates': titles, 'title': titles[0], 'body': body, 'headings': re.findall(r'^##+ (.+)$', body, re.M), 'tags': ['ChatGPT', 'note運営', '副業', '公開実験', '運営記録'], 'reason': f'取得実績と比較可能性に基づくカテゴリ{category}の選択。施策の実施や成功は推測しない。', 'hypothesis': hypothesis, 'next_kpi': ['同じ集計範囲のPV', 'スキ', 'コメント', '売上'], 'thumbnail_text': 'AIにnoteを任せてみた', 'thumbnail_prompt': '公開実験の記録を表すシンプルな図。未確認の数値、収益実績、成功表現を入れない。'}


def save_draft(directory, snapshot, article):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = snapshot['collected_at'][:10] + '-' + snapshot['snapshot_id'][:12]
    path = directory / (stem + '.md')
    front = {'title': article['title'], 'created_at': now(), 'source_metrics': snapshot['snapshot_id'], 'tags': article['tags'], 'status': 'draft'}
    # JSON objects are valid YAML flow mappings.
    path.write_text('---\n' + json.dumps(front, ensure_ascii=False) + '\n---\n\n' + article['body'], encoding='utf-8')
    atomic_json(directory / (stem + '.metadata.json'), dict(article, source_metrics=snapshot['snapshot_id']))
    return path
