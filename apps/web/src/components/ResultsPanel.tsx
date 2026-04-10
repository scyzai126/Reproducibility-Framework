'use client';

import { useState } from 'react';
import type { RunRecord, SubjectResult } from '@/lib/types';

function Badge({ label, value }: { label: string; value: string }) {
  return (
    <span className="text-xs bg-gray-700 text-gray-300 px-2 py-0.5 rounded-full">
      <span className="text-gray-500">{label}: </span>
      {value}
    </span>
  );
}

function GroupCard({ group }: { group: SubjectResult }) {
  const [expanded, setExpanded] = useState(false);
  const hasError = !!group.error;
  const subjectCount = group.subjects.length;
  const columns = subjectCount > 0 ? Object.keys(group.subjects[0]) : [];

  return (
    <div className="bg-gray-800 rounded-xl border border-gray-700 overflow-hidden">
      <div className="px-5 py-4 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="font-semibold text-gray-100 truncate">
            Group {group.group_id}:{' '}
            <span className="text-gray-200">{group.group_name}</span>
          </h3>
          <div className="flex flex-wrap gap-1.5 mt-2">
            {group.arm_accession && <Badge label="Arm" value={group.arm_accession} />}
            {group.experiment_accession && (
              <Badge label="Exp" value={group.experiment_accession} />
            )}
            {group.tissue_type && <Badge label="Tissue" value={group.tissue_type} />}
            {group.condition && <Badge label="Condition" value={group.condition} />}
          </div>
        </div>
        <div className="text-right flex-shrink-0">
          {hasError ? (
            <span className="text-red-400 text-sm font-medium">Error</span>
          ) : (
            <>
              <span
                className={`text-3xl font-bold tabular-nums ${
                  subjectCount > 0 ? 'text-blue-400' : 'text-gray-600'
                }`}
              >
                {subjectCount}
              </span>
              <p className="text-xs text-gray-500">subjects</p>
            </>
          )}
        </div>
      </div>

      {hasError && (
        <div className="px-5 pb-4 text-sm text-red-400 bg-red-900/10">{group.error}</div>
      )}

      {!hasError && subjectCount > 0 && (
        <div className="border-t border-gray-700">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="w-full px-5 py-2.5 text-left text-xs text-gray-400 hover:text-gray-200 hover:bg-gray-750 flex items-center gap-2 transition-colors"
          >
            <span
              className={`transition-transform duration-200 inline-block ${
                expanded ? 'rotate-90' : ''
              }`}
            >
              ▶
            </span>
            {expanded ? 'Hide' : 'Show'} subject list
          </button>
          {expanded && (
            <div className="px-5 pb-4 overflow-x-auto">
              <table className="text-xs w-full">
                <thead>
                  <tr className="text-gray-500 border-b border-gray-700">
                    {columns.map((k) => (
                      <th key={k} className="text-left py-2 pr-4 font-medium whitespace-nowrap">
                        {k}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {group.subjects.map((row, i) => (
                    <tr key={i} className="border-b border-gray-800 hover:bg-gray-700/50">
                      {columns.map((k) => (
                        <td key={k} className="py-1.5 pr-4 text-gray-300 whitespace-nowrap">
                          {String(row[k] ?? '')}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface Props {
  run: RunRecord;
}

export function ResultsPanel({ run }: Props) {
  const { study_accession, subject_results } = run.result;
  const totalSubjects = subject_results.reduce((sum, g) => sum + g.subjects.length, 0);
  const errorCount = subject_results.filter((g) => g.error).length;

  return (
    <div className="p-6 max-w-4xl mx-auto w-full">
      <div className="mb-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-gray-100">
              Study:{' '}
              <span className="text-blue-400 font-mono">{study_accession || '—'}</span>
            </h2>
            <p className="text-sm text-gray-500 mt-1">{run.filename}</p>
          </div>
          <div className="text-right text-sm text-gray-400 flex-shrink-0">
            <p>
              {subject_results.length} group{subject_results.length !== 1 ? 's' : ''}
            </p>
            <p className="text-blue-400 font-medium">{totalSubjects} subjects total</p>
            {errorCount > 0 && (
              <p className="text-red-400">{errorCount} error{errorCount !== 1 ? 's' : ''}</p>
            )}
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-4">
        {subject_results.map((group) => (
          <GroupCard key={group.group_id} group={group} />
        ))}
        {subject_results.length === 0 && (
          <div className="text-center py-12 text-gray-600">No groups found in this signature.</div>
        )}
      </div>
    </div>
  );
}
