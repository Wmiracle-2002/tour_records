"""Summarize nested latency spans without double-counting child operations."""
import argparse
import json
from pathlib import Path


def summarize(directory):
    root = Path(directory)
    results = json.loads((root / 'results.json').read_text(encoding='utf-8'))
    spans = json.loads((root / 'spans.json').read_text(encoding='utf-8'))
    calls = json.loads((root / 'llm-calls.json').read_text(encoding='utf-8'))
    deltas = json.loads((root / 'stream-first-delta.json').read_text(encoding='utf-8'))
    ledger = {item['id']: item for item in json.loads((root / 'usage-ledger.json').read_text(encoding='utf-8'))}
    rows = []
    for result in results:
        case_id = result['id']
        case_spans = [span for span in spans if span['case_id'] == case_id]
        runtimes = [span for span in case_spans if span['name'] == 'agent_runtime']
        assert len(runtimes) == 1, (case_id, 'Missing runtime timing')
        runtime = runtimes[0]
        direct = [span for span in case_spans if span['parent'] == runtime['id']]
        stages = {}
        for span in direct:
            stages[span['name']] = stages.get(span['name'], 0) + span['duration_ms']
        stage_sum = sum(stages.values())
        assert stage_sum <= runtime['duration_ms'] + 0.5, 'Nested spans counted twice'
        searches = [span for span in case_spans if span['name'] == 'poi_search']
        search_ms = sum(span['duration_ms'] for span in searches)
        # Only an upper-bound estimate: query scheduling/connection contention may
        # reduce the saving; error handling and persistence stay on the caller.
        parallel_upper_ms = search_ms - max((span['duration_ms'] for span in searches), default=0)
        llm = [span for span in case_spans if span['name'].startswith(('llm:', 'llm_stream:'))]
        requests = [call for call in calls if call['case_id'] == case_id and 'quota_id' in call]
        tokens = sum((ledger[call['quota_id']]['input_tokens'] or 0) + (ledger[call['quota_id']]['output_tokens'] or 0) for call in requests)
        generation = [span for span in llm if span['name'].startswith('llm_stream:')]
        first = [item for item in deltas if item['case_id'] == case_id]
        rows.append({'case_id': case_id, 'message': result['message'], 'terminal': result['final_event'],
            'request_id': result['request_id'], 'first_body_ms': result.get('first_body_ms'),
            'completion_ms': result.get('completion_ms'), 'termination_ms': result.get('termination_ms'),
            'runtime_ms': runtime['duration_ms'], 'direct_stages_ms': stages,
            'runtime_unattributed_ms': runtime['duration_ms'] - stage_sum,
            'http_sse_other_ms': result['termination_ms'] - runtime['duration_ms'],
            'llm_operations': [{'name': span['name'], 'duration_ms': span['duration_ms'], 'status': span['status'],
                                'error_type': span.get('error_type')} for span in llm],
            'llm_total_ms': sum(span['duration_ms'] for span in llm),
            'llm_http_reservations': len(requests), 'settled_tokens': tokens,
            'poi_queries': [{'kind': span.get('kind'), 'duration_ms': span['duration_ms']} for span in searches],
            'amap_http_ms': sum(span['duration_ms'] for span in case_spans if span['name'] == 'amap_http'),
            'poi_parallel_saving_upper_ms': parallel_upper_ms,
            'stream_first_delta_from_generation_ms': first[0]['at_ms'] - generation[0]['start_ms'] if first and generation else None,
            'stage_outcomes': [event for event in result['agent_events'] if event['event'] == 'stage_completed'],
            'quota_rejected_operations': sum(call.get('quota_rejected', False) for call in calls if call['case_id'] == case_id)})
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory')
    args = parser.parse_args()
    rows = summarize(args.directory)
    Path(args.directory, 'latency-summary.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(rows, ensure_ascii=False, indent=2))
