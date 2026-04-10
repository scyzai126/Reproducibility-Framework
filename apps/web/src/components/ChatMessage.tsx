'use client';

import { useState } from 'react';
import { AgentResponse, SubjectResult, ClaimResult, PaperClaim, ChatMessage } from '@/lib/types';

interface Props {
  message: ChatMessage;
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

function AssistantMessage({ message }: Props) {
  return (
    <div className="flex gap-3">
      <div className="w-8 h-8 rounded-full bg-emerald-600 flex items-center justify-center flex-shrink-0 mt-1 text-white text-xs font-bold">
        AI
      </div>
      <div className="flex-1 min-w-0 pt-1">
        {message.isLoading ? (
          <div className="flex items-center gap-1 py-1">
            <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
            <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
            <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
        ) : message.error ? (
          <div className="text-red-400 text-sm">
            <span className="font-medium">Error: </span>
            {message.error}
          </div>
        ) : message.result ? (
          <ResultsDisplay result={message.result} />
        ) : null}
      </div>
    </div>
  );
}

function Badge({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <span className="inline-flex items-center gap-1 text-xs bg-gray-100 text-gray-600 rounded-md px-2 py-0.5">
      <span className="text-gray-400">{label}</span>
      <span className="font-medium text-gray-700 font-mono">{value}</span>
    </span>
  );
}

function GroupCard({ group, index }: { group: SubjectResult; index: number }) {
  const [expanded, setExpanded] = useState(true);
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
              group.error ? 'text-red-500' : count > 0 ? 'text-emerald-600' : 'text-gray-400'
            }`}>
              {group.error ? 'error' : `${count} subject${count !== 1 ? 's' : ''}`}
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

      {expanded && group.error && (
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
              {group.subjects.map((s, i) => (
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
          <span className="text-xs font-medium text-gray-500 mb-1 block">Claim {index + 1}</span>
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
        </div>
      )}
    </div>
  );
}

function ResultsDisplay({ result }: { result: AgentResponse }) {
  const [copied, setCopied] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const json = JSON.stringify(result, null, 2);

  const isPaperQuestion = result.paper_claims && result.paper_claims.length > 0;
  const isClaims = !isPaperQuestion && result.claims && result.claims.length > 0;

  const totalSubjects = isClaims
    ? result.claims.reduce((n, c) => n + c.subject_results.reduce((m, g) => m + (g.subjects?.length ?? 0), 0), 0)
    : result.subject_results.reduce((n, g) => n + (g.subjects?.length ?? 0), 0);

  const groupCount = isClaims
    ? result.claims.reduce((n, c) => n + c.subject_results.length, 0)
    : result.subject_results.length;

  const handleCopy = () => {
    navigator.clipboard.writeText(json);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="text-sm space-y-3">
      {/* Header */}
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

      {/* Cards */}
      {!showRaw && (
        <div className="space-y-2">
          {isPaperQuestion ? (
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

export default function ChatMessageComponent({ message }: Props) {
  if (message.role === 'user') return <UserMessage message={message} />;
  return <AssistantMessage message={message} />;
}
