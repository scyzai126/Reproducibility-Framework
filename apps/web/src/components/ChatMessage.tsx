'use client';

import { useState, useEffect } from 'react';
import { AgentResponse, SubjectResult, ClaimResult, Comparison, PaperClaim, ChatMessage, ClaimFailures } from '@/lib/types';
import CompletenessReport from '@/components/CompletenessReport';

interface Props {
  message: ChatMessage;
  /** Sends a follow-up message, e.g. the paper picked from a study's list. */
  onSend?: (text: string) => void;
  disabled?: boolean;
}

function UserMessage({ message }: Props) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] bg-gray-100 rounded-2xl px-4 py-3 text-sm text-gray-800">
        {message.filename && message.filename !== 'input.json' ? (
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="text-blue-500">📄</span>
              <span>{message.filename}</span>
            </div>
            {message.content && (
              <p className="text-sm text-gray-700">{message.content}</p>
            )}
          </div>
        ) : message.content ? (
          <pre className="whitespace-pre-wrap font-mono text-xs max-h-40 overflow-auto">{message.content}</pre>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-blue-500">📄</span>
            <span>input.json</span>
          </div>
        )}
      </div>
    </div>
  );
}

const WORKFLOW_STEPS = [
  { label: 'Reading and parsing the input',                          delay: 0 },
  { label: 'Fetching full paper text from PubMed/PMC',               delay: 1500 },
  { label: 'Extracting claims and participant groups',                delay: 3000 },
  { label: 'Syncing study data from ImmPort',                        delay: 4500 },
  { label: 'Resolving terms to ImmPort accessions',                  delay: 6000 },
  { label: 'Querying matched subjects from the database',            delay: 7500 },
  { label: 'Generating the final report',                            delay: 9500 },
];

function WorkflowProgress() {
  const [activeStep, setActiveStep] = useState(0);

  useEffect(() => {
    const timers = WORKFLOW_STEPS.slice(1).map((step, i) =>
      setTimeout(() => setActiveStep(i + 1), step.delay)
    );
    return () => timers.forEach(clearTimeout);
  }, []);

  return (
    <div className="space-y-2 py-1">
      {WORKFLOW_STEPS.map((step, i) => {
        const done = i < activeStep;
        const active = i === activeStep;
        return (
          <div key={i} className={`flex items-center gap-2.5 text-sm transition-opacity ${i > activeStep ? 'opacity-30' : 'opacity-100'}`}>
            {done ? (
              <svg className="w-4 h-4 text-emerald-500 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            ) : active ? (
              <svg className="w-4 h-4 text-gray-400 flex-shrink-0 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
              </svg>
            ) : (
              <div className="w-4 h-4 rounded-full border-2 border-gray-200 flex-shrink-0" />
            )}
            <span className={active ? 'text-gray-700 font-medium' : done ? 'text-gray-400' : 'text-gray-300'}>
              {step.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function AssistantMessage({ message, onSend, disabled }: Props) {
  return (
    <div className="flex gap-3">
      <div className="w-8 h-8 rounded-full bg-emerald-600 flex items-center justify-center flex-shrink-0 mt-1 text-white text-xs font-bold">
        AI
      </div>
      <div className="flex-1 min-w-0 pt-1">
        {message.isLoading ? (
          <WorkflowProgress />
        ) : message.error ? (
          <div className="text-red-400 text-sm">
            <span className="font-medium">Error: </span>
            {message.error}
          </div>
        ) : message.result?.type === 'paper_choice' ? (
          <PaperChoice result={message.result} onSend={onSend} disabled={disabled} />
        ) : message.result?.type === 'immport_confirm' ? (
          <ImmportConfirm result={message.result} onSend={onSend} disabled={disabled} />
        ) : message.result?.type === 'clarification' ? (
          <p className="text-sm text-gray-700 whitespace-pre-line">{message.result.question}</p>
        ) : message.result?.type === 'pdf_upload_required' ? (
          <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 space-y-2">
            <div className="flex items-center gap-2">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="flex-shrink-0 text-blue-500">
                <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/>
              </svg>
              <p className="text-sm font-medium text-blue-700">PDF upload required</p>
            </div>
            <p className="text-xs text-blue-600 leading-relaxed">
              This paper is not available as open-access XML in PubMed Central.
              Please upload the PDF using the paperclip button below to continue analysis.
            </p>
            {message.result.pubmed_id && (
              <p className="text-xs text-blue-500 font-mono bg-blue-100 rounded px-2 py-1 inline-block">
                Rename the file to: PMID{message.result.pubmed_id}.pdf
              </p>
            )}
            {message.result.study_accession && (
              <p className="text-xs text-blue-400">
                Study: <span className="font-mono">{message.result.study_accession}</span>
              </p>
            )}
          </div>
        ) : message.result?.type === 'multi_paper' ? (
          <div className="space-y-4">
            <p className="text-xs text-gray-500 font-medium">
              {message.result.papers?.length} papers found for this study
            </p>
            {message.result.papers?.map((paper, i) => (
              <div key={i} className="border border-gray-200 rounded-xl overflow-hidden">
                <div className="bg-gray-50 px-4 py-2 border-b border-gray-200">
                  <span className="text-xs font-semibold text-gray-600">
                    Paper {i + 1}{paper.pubmed_id ? ` — PMID ${paper.pubmed_id}` : ''}
                  </span>
                </div>
                <div className="p-3">
                  {paper.type === 'pdf_upload_required' ? (
                    <p className="text-xs text-blue-600">
                      PDF upload required — rename to PMID{paper.pubmed_id}.pdf
                    </p>
                  ) : (
                    <ResultsDisplay result={paper} />
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : message.result ? (
          <ResultsDisplay result={message.result} />
        ) : null}
      </div>
    </div>
  );
}

function PaperChoice({ result, onSend, disabled }: { result: AgentResponse; onSend?: (text: string) => void; disabled?: boolean }) {
  const options = result.paper_options ?? [];
  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden">
      <p className="px-4 py-2.5 border-b border-gray-200 text-sm text-gray-700">{result.question}</p>
      <ul className="divide-y divide-gray-100">
        {options.map((paper) => (
          <li key={paper.pubmed_id}>
            <button
              onClick={() => onSend?.(`${result.study_accession} PMID:${paper.pubmed_id}`)}
              disabled={disabled || !onSend || !paper.usable}
              className="w-full text-left px-4 py-2.5 hover:bg-gray-50 transition-colors disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:opacity-60"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-xs text-gray-500">PMID {paper.pubmed_id}</span>
                {paper.year && <span className="text-xs text-gray-400">{paper.year}</span>}
                {paper.cached ? (
                  <span className="text-xs text-emerald-700">claims cached · free</span>
                ) : paper.local_pdf ? (
                  <span className="text-xs text-gray-400">PDF on disk · new run</span>
                ) : paper.usable ? (
                  <span className="text-xs text-gray-400">fetched from PMC · new run</span>
                ) : null}
              </div>
              <p className="text-sm text-gray-800 mt-0.5">{paper.title ?? '(no title)'}</p>
              {paper.unusable_reason && (
                <p className="text-xs text-amber-700 mt-1">{paper.unusable_reason}</p>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ImmportConfirm({ result, onSend, disabled }: { result: AgentResponse; onSend?: (text: string) => void; disabled?: boolean }) {
  const [answer, setAnswer] = useState<'yes' | 'no' | null>(null);
  const title = result.situation === 'multiple_studies'
    ? 'This paper maps to several ImmPort studies'
    : 'This paper is not in ImmPort';
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 space-y-2">
      <p className="text-sm font-medium text-amber-800">{title}</p>
      <p className="text-xs text-amber-700 leading-relaxed">{result.question}</p>
      {answer === null ? (
        <div className="flex gap-2 pt-1">
          <button
            onClick={() => { setAnswer('yes'); onSend?.(`PMID:${result.pubmed_id} claims-only`); }}
            disabled={disabled || !onSend}
            className="text-xs font-medium text-white bg-amber-600 hover:bg-amber-700 rounded px-3 py-1.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Yes, extract claims only
          </button>
          <button
            onClick={() => setAnswer('no')}
            disabled={disabled}
            className="text-xs text-amber-700 border border-amber-300 hover:bg-amber-100 rounded px-3 py-1.5 transition-colors disabled:opacity-50"
          >
            No
          </button>
        </div>
      ) : (
        <p className="text-xs text-amber-600">{answer === 'yes' ? 'Extracting claims only…' : 'Cancelled — nothing was run.'}</p>
      )}
    </div>
  );
}

function formatBadgeValue(label: string, value: string): string {
  if (label === 'time point') {
    const range = value.match(/^(\d+(?:\.\d+)?)days<time<(\d+(?:\.\d+)?)days$/);
    if (range) return `day ${range[1]} – day ${range[2]}`;
  }
  return value;
}

function Badge({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <span className="inline-flex items-center gap-1 text-xs bg-gray-100 text-gray-600 rounded-md px-2 py-0.5">
      <span className="text-gray-400">{label}</span>
      <span className="font-medium text-gray-700 font-mono">{formatBadgeValue(label, value)}</span>
    </span>
  );
}

function GroupCard({ group, index }: { group: SubjectResult; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const count = group.subjects?.length ?? 0;
  const resolvers = group.resolvers ?? {};

  return (
    <div className="rounded-xl border border-gray-200 overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-start justify-between gap-3 px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-gray-800 text-sm">Group {index}</span>
            <span className={`text-xs font-medium ${
              group.skipped ? 'text-amber-500' : group.error ? 'text-red-500' : count > 0 ? 'text-emerald-600' : 'text-gray-400'
            }`}>
              {group.skipped ? 'skipped' : group.error ? 'error' : `${count} subject${count !== 1 ? 's' : ''}`}
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5 mt-2">
            {Object.entries(resolvers).map(([k, v]) => (
              <Badge key={k} label={k.replace(/_accession$/, '').replace(/_/g, ' ')} value={v} />
            ))}
          </div>
        </div>
        <svg
          xmlns="http://www.w3.org/2000/svg" width="14" height="14"
          viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          className={`flex-shrink-0 mt-1 text-gray-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {expanded && group.skipped && (
        <div className="px-4 py-3 text-xs text-amber-600 bg-amber-50">{group.error}</div>
      )}
      {expanded && group.error && !group.skipped && (
        <div className="px-4 py-3 text-xs text-red-500 bg-red-50">{group.error}</div>
      )}

      {expanded && !group.error && count > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-white border-b border-gray-100">
                <th className="text-left px-4 py-2 text-gray-400 font-medium">#</th>
                <th className="text-left px-4 py-2 text-gray-400 font-medium">subject_accession</th>
                <th className="text-left px-4 py-2 text-gray-400 font-medium">biosample_accession</th>
                <th className="text-left px-4 py-2 text-gray-400 font-medium">expsample_accession</th>
              </tr>
            </thead>
            <tbody>
              {(group.subjects ?? []).map((s, i) => (
                <tr key={i} className={`border-b border-gray-50 ${i % 2 === 0 ? 'bg-white' : 'bg-gray-50/50'}`}>
                  <td className="px-4 py-2 text-gray-300">{i + 1}</td>
                  <td className="px-4 py-2 font-mono text-blue-600">{s.subject_accession}</td>
                  <td className="px-4 py-2 font-mono text-gray-500">{s.biosample_accession ?? '—'}</td>
                  <td className="px-4 py-2 font-mono text-gray-500">{s.expsample_accession ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {expanded && !group.error && count === 0 && (
        <div className="px-4 py-3 text-xs text-gray-400 italic">No subjects found</div>
      )}
    </div>
  );
}

function PaperClaimCard({ claim, index }: { claim: PaperClaim; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const sources = claim.sources ?? [];

  return (
    <div className="rounded-xl border border-gray-200 overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-start justify-between gap-3 px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
      >
        <div className="flex-1 min-w-0">
          <span className="text-xs font-medium text-gray-500 mb-1 block">
            Claim {index + 1}
            {claim.claim_type && <span className="ml-2 font-mono font-normal text-gray-400">{claim.claim_type}</span>}
          </span>
          <p className="text-xs text-gray-800">{claim.claim_text}</p>
        </div>
        {sources.length > 0 && (
          <svg
            xmlns="http://www.w3.org/2000/svg" width="14" height="14"
            viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
            className={`flex-shrink-0 mt-1 text-gray-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        )}
      </button>
      {expanded && sources.length > 0 && (
        <div className="px-4 py-3 space-y-2 bg-white border-t border-gray-100">
          {sources.map((s, i) => (
            <div key={i} className="text-xs text-gray-500">
              <span className="font-medium text-gray-600">{s.section ?? s.type}</span>
              {s.quote && <p className="mt-0.5 italic text-gray-400">"{s.quote}"</p>}
              {s.ref && <p className="mt-0.5 text-gray-400">{s.ref}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ComparisonPill({ comparison }: { comparison: Comparison }) {
  const [open, setOpen] = useState(false);
  const [a, b] = comparison.contrast;

  return (
    <div className="inline-block">
      <button
        onClick={() => setOpen((v) => !v)}
        title="View finding"
        className={`text-xs border rounded px-2 py-0.5 font-mono transition-colors ${
          open
            ? 'bg-violet-200 text-violet-800 border-violet-300'
            : 'bg-violet-50 text-violet-700 border-violet-200 hover:bg-violet-100'
        }`}
      >
        {a} vs {b}
      </button>
      {open && comparison.finding && (
        <div className="mt-1.5 px-3 py-2 rounded-lg bg-violet-50 border border-violet-200 text-xs text-gray-700 leading-relaxed">
          <span className="font-semibold text-violet-700">Result: </span>{comparison.finding}
        </div>
      )}
    </div>
  );
}

function ClaimCard({ claim }: { claim: ClaimResult }) {
  const [expanded, setExpanded] = useState(true);
  const totalSubjects = claim.subject_results.reduce((n, g) => n + (g.subjects?.length ?? 0), 0);

  return (
    <div className="rounded-xl border border-gray-200 overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-start justify-between gap-3 px-4 py-3 bg-blue-50 hover:bg-blue-100 transition-colors text-left"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="text-xs font-medium text-blue-600 bg-blue-100 px-2 py-0.5 rounded">
              Claim {claim.claim_id}
            </span>
            {claim.study_design && (
              <span className="text-xs text-gray-500">{claim.study_design}</span>
            )}
            <span className="text-xs text-emerald-600 font-medium">{totalSubjects} subjects</span>
          </div>
          <p className="text-xs text-gray-700">{claim.claim_text}</p>
        </div>
        <svg
          xmlns="http://www.w3.org/2000/svg" width="14" height="14"
          viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          className={`flex-shrink-0 mt-1 text-gray-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {expanded && (
        <div className="p-3 space-y-2 bg-white">
          {claim.subject_results.map((group, i) => (
            <GroupCard key={i} group={group} index={i} />
          ))}
          {claim.subject_results.length === 0 && (
            <div className="text-xs text-gray-400 italic px-1">No groups found</div>
          )}
          {(claim.comparison ?? []).length > 0 && (
            <div className="pt-1 flex flex-wrap gap-1.5">
              <span className="text-xs text-gray-400 self-start mt-0.5">Comparisons:</span>
              {(claim.comparison as Comparison[]).map((c, i) => (
                <ComparisonPill key={i} comparison={c} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ResultsDisplay({ result }: { result: AgentResponse }) {
  const [copied, setCopied] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const [activeTab, setActiveTab] = useState<'results' | 'completeness'>('results');
  const [claimFailures, setClaimFailures] = useState<ClaimFailures[]>([]);

  const json = JSON.stringify(result, null, 2);
  const isClaimsOnly = result.type === 'claims_only';
  const isNoImmport = result.type === 'no_immport' || isClaimsOnly;
  const isPaperQuestion = !isNoImmport && result.paper_claims && result.paper_claims.length > 0;
  const isClaims = !isNoImmport && !isPaperQuestion && result.claims && result.claims.length > 0;
  const hasCompleteness = !!result.completeness;
  const failureCount = result.completeness?.claims_with_failures ?? 0;

  const totalSubjects = isClaims
    ? result.claims.reduce((n, c) => n + c.subject_results.reduce((m, g) => m + (g.subjects?.length ?? 0), 0), 0)
    : result.subject_results.reduce((n, g) => n + (g.subjects?.length ?? 0), 0);

  const groupCount = isClaims
    ? result.claims.reduce((n, c) => n + c.subject_results.length, 0)
    : result.subject_results.length;

  useEffect(() => {
    if (activeTab !== 'completeness' || !hasCompleteness) return;
    fetch('/backend/agent/completeness-report')
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data?.claims) setClaimFailures(data.claims); })
      .catch(() => {});
  }, [activeTab, hasCompleteness]);

  const handleCopy = () => {
    navigator.clipboard.writeText(json);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="text-sm space-y-3">
      {/* No-ImmPort notice */}
      {isNoImmport && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 flex items-start gap-2">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="flex-shrink-0 mt-0.5 text-amber-500">
            <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
          <div>
            <p className="text-xs font-medium text-amber-700">
              {isClaimsOnly ? `Claims only — PMID ${result.pubmed_id}` : 'This paper is not associated with any dataset in ImmPort'}
            </p>
            <p className="text-xs text-amber-600 mt-0.5">
              {isClaimsOnly
                ? 'Claims were extracted from the paper. No grouping or subject matching was run.'
                : 'Claims have been extracted from the paper, but no subject-level data is available for matching.'}
            </p>
          </div>
        </div>
      )}

      {/* Header */}
      {!isNoImmport && (
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-gray-500">Study</span>
            <span className="text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded text-xs">
              {result.study_accession}
            </span>
            <span className="text-gray-300">·</span>
            {isPaperQuestion && (
              <>
                <span className="text-gray-500">{result.paper_claims.length} paper claims</span>
                <span className="text-gray-300">·</span>
              </>
            )}
            {isClaims && (
              <>
                <span className="text-gray-500">{result.claims.length} claims</span>
                <span className="text-gray-300">·</span>
              </>
            )}
            <span className="text-gray-500">{groupCount} groups</span>
            <span className="text-gray-300">·</span>
            <span className="text-gray-500">{totalSubjects} total subjects</span>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setShowRaw((v) => !v)}
              className="text-xs text-gray-400 hover:text-gray-700 border border-gray-200 hover:border-gray-400 rounded px-2 py-1 transition-colors"
            >
              {showRaw ? 'Hide JSON' : 'View JSON'}
            </button>
            <button
              onClick={handleCopy}
              className="text-xs text-gray-400 hover:text-gray-700 border border-gray-200 hover:border-gray-400 rounded px-2 py-1 transition-colors"
            >
              {copied ? '✓ Copied' : 'Copy JSON'}
            </button>
          </div>
        </div>
      )}

      {/* Tab switcher — only when completeness data is present */}
      {!isNoImmport && hasCompleteness && (
        <div className="flex gap-1 border-b border-gray-200 -mb-1">
          <button
            onClick={() => setActiveTab('results')}
            className={`px-3 py-1.5 text-xs font-medium border-b-2 -mb-px transition-colors ${
              activeTab === 'results'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-400 hover:text-gray-600'
            }`}
          >
            Results
          </button>
          <button
            onClick={() => setActiveTab('completeness')}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border-b-2 -mb-px transition-colors ${
              activeTab === 'completeness'
                ? 'border-amber-500 text-amber-600'
                : 'border-transparent text-gray-400 hover:text-gray-600'
            }`}
          >
            Completeness
            {failureCount > 0 ? (
              <span className="bg-amber-100 text-amber-700 rounded-full px-1.5 py-px text-[10px] font-semibold leading-none">
                {failureCount}
              </span>
            ) : (
              <span className="bg-emerald-100 text-emerald-600 rounded-full px-1 py-px leading-none">
                <svg xmlns="http://www.w3.org/2000/svg" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </span>
            )}
          </button>
        </div>
      )}

      {/* Completeness tab */}
      {!isNoImmport && hasCompleteness && activeTab === 'completeness' && (
        <CompletenessReport summary={result.completeness!} claimFailures={claimFailures} />
      )}

      {/* Results tab (or default when no completeness data) */}
      {(isNoImmport || !hasCompleteness || activeTab === 'results') && !showRaw && (
        <div className="space-y-2">
          {isNoImmport ? (
            <>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{result.paper_claims.length} Claims</p>
              {result.paper_claims.map((c, i) => <PaperClaimCard key={i} claim={c} index={i} />)}
            </>
          ) : isPaperQuestion ? (
            <>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Paper Claims</p>
              {result.paper_claims.map((c, i) => <PaperClaimCard key={i} claim={c} index={i} />)}
              {result.subject_results.length > 0 && (
                <>
                  <p className="text-xs font-medium text-gray-500 uppercase tracking-wide pt-2">Matched Subjects</p>
                  {result.subject_results.map((g, i) => <GroupCard key={i} group={g} index={i} />)}
                </>
              )}
            </>
          ) : isClaims
            ? result.claims.map((claim, i) => <ClaimCard key={i} claim={claim} />)
            : result.subject_results.map((group, i) => <GroupCard key={i} group={group} index={i} />)
          }
        </div>
      )}

      {/* No-ImmPort copy button */}
      {isNoImmport && (
        <div className="flex gap-2">
          <button onClick={() => setShowRaw((v) => !v)} className="text-xs text-gray-400 hover:text-gray-700 border border-gray-200 hover:border-gray-400 rounded px-2 py-1 transition-colors">
            {showRaw ? 'Hide JSON' : 'View JSON'}
          </button>
          <button onClick={handleCopy} className="text-xs text-gray-400 hover:text-gray-700 border border-gray-200 hover:border-gray-400 rounded px-2 py-1 transition-colors">
            {copied ? '✓ Copied' : 'Copy JSON'}
          </button>
        </div>
      )}

      {/* Raw JSON */}
      {showRaw && (
        <div className="rounded-xl border border-gray-200 overflow-hidden">
          <div className="bg-gray-50 px-4 py-2 border-b border-gray-200 text-xs text-gray-400 font-mono">
            application/json
          </div>
          <pre className="overflow-auto max-h-[60vh] p-4 text-xs font-mono text-gray-800 bg-white leading-relaxed">
            {json}
          </pre>
        </div>
      )}
    </div>
  );
}

export default function ChatMessageComponent({ message, onSend, disabled }: Props) {
  if (message.role === 'user') return <UserMessage message={message} />;
  return <AssistantMessage message={message} onSend={onSend} disabled={disabled} />;
}
