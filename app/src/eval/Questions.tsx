import { useMemo } from 'react';
import { type Data, type Result } from './data';

const number = (value: number | null | undefined) => value == null ? 'Not found'
  : Number(value).toLocaleString('en-US', { maximumFractionDigits: 4 });
const timestamp = (value: string | Date) => {
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? 0 : time;
};
const key = (r: Result) => `${r.questionId}\u0000${r.attempt}`;

function Check({ label, status, reason }: { label: string; status: string; reason: string }) {
  const state = status?.toLowerCase() || 'skipped';
  return (
    <div className="check">
      <div>
        <strong>{label}</strong>
        <span className={`badge ${state}`}>{status || 'not checked'}</span>
      </div>
      <p>{reason || 'No reason recorded'}</p>
    </div>
  );
}

export default function Questions({ data, currentId, selected, onSelect }: {
  data: Data | null; currentId: string | undefined; selected: string; onSelect: (key: string) => void;
}) {
  const answers = useMemo(() => (data?.results || []).filter(r => r.runId === currentId).sort(
    (a, b) => a.questionId.localeCompare(b.questionId) || a.attempt - b.attempt,
  ), [data, currentId]);
  const detail = answers.find(r => key(r) === selected) || answers[0];
  const queries = (data?.queries || []).filter(q => detail && q.runId === detail.runId
    && q.questionId === detail.questionId && q.attempt === detail.attempt)
    .sort((a, b) => timestamp(a.timestamp) - timestamp(b.timestamp));

  if (!answers.length) return <div className="message">No answers recorded for this run.</div>;

  return (
    <div className="question-layout">
      <section className="panel question-list">
        <div className="section-title">
          <div>
            <h2>All questions</h2>
            <p>{answers.length} answers in this run · select a question to inspect its evidence</p>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Question</th>
                <th>Attempt</th>
                <th>Verdict</th>
                <th>Value check</th>
                <th>Citation check</th>
                <th>Model check</th>
              </tr>
            </thead>
            <tbody>
              {answers.map(r => (
                <tr key={key(r)} className={detail && key(detail) === key(r) ? 'selected' : ''}>
                  <td>
                    <button className="question-select" onClick={() => onSelect(key(r))}
                      aria-pressed={!!detail && key(detail) === key(r)}>
                      {r.questionId}
                    </button>
                  </td>
                  <td>{r.attempt}</td>
                  <td>
                    <span className={`badge ${r.verdict?.toLowerCase()}`}>{r.verdict}</span>
                  </td>
                  <td>{r.valueReason || 'No reason recorded'}</td>
                  <td>{r.citationReason || 'No reason recorded'}</td>
                  <td>{r.modelReason || 'No reason recorded'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {detail && (
        <section className="panel detail">
          <div className="detail-top">
            <div>
              <span className="eyebrow">QUESTION {detail.questionId} · ATTEMPT {detail.attempt}</span>
              <h2>{detail.question}</h2>
            </div>
            <span className={`badge ${detail.verdict?.toLowerCase()}`}>{detail.verdict}</span>
          </div>
          <div className="answer-box">
            <div className="detail-label">COPILOT'S ANSWER</div>
            <p>{detail.answer || 'No answer recorded.'}</p>
          </div>
          <div className="value-pair">
            <div>
              <span>EXPECTED VALUE</span>
              <strong>{number(detail.expected)}</strong>
            </div>
            <div>
              <span>FOUND VALUE</span>
              <strong>{number(detail.found)}</strong>
            </div>
          </div>
          <h3>Evaluation checks</h3>
          <div className="checks">
            <Check label="Value" status={detail.valueCheck} reason={detail.valueReason} />
            <Check label="Citation" status={detail.citationCheck} reason={detail.citationReason} />
            <Check label="Model" status={detail.modelCheck} reason={detail.modelReason} />
          </div>
          <h3>Evidence</h3>
          <div className="evidence">
            <div>
              <span>CITED REPORTS</span>
              <p>{detail.citedReports || 'None recorded'}</p>
            </div>
            <div>
              <span>QUERIED MODELS</span>
              <p>{detail.queriedModels || 'None recorded'}</p>
            </div>
          </div>
          <div className="detail-label dax-label">
            DAX QUERIES <span>{queries.length}</span>
          </div>
          {queries.length ? queries.map((query, i) => (
            <div className="query" key={i}>
              <div>
                {query.semanticModel || 'Unknown model'}{' '}
                {query.durationMs != null && <span>· {number(query.durationMs)} ms</span>}
              </div>
              <pre>{query.dax || 'No query text recorded'}</pre>
            </div>
          )) : <p className="subtle">No DAX queries recorded for this answer.</p>}
        </section>
      )}
    </div>
  );
}
