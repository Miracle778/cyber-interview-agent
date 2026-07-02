import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { approveVersion, createProfileRun, getRun } from "../lib/api";
import { useRunEvents } from "../hooks/useRunEvents";

export function Profile() {
  const [text, setText] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const { events, terminal } = useRunEvents(runId);

  const createMutation = useMutation({
    mutationFn: (input: string) => createProfileRun(input),
    onSuccess: (response) => setRunId(response.run_id),
  });

  const runQuery = useQuery({
    queryKey: ["profile", runId],
    queryFn: () => getRun(runId!),
    enabled: Boolean(runId && terminal),
  });

  const approveMutation = useMutation({
    mutationFn: (versionId: string) => approveVersion(versionId),
  });

  const pending = runQuery.data?.pending_version;

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 p-4">
      <h1 className="text-xl font-bold">Profile 抽取</h1>
      <textarea
        aria-label="个人资料文本"
        className="min-h-36 w-full border p-2"
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="粘贴个人资料..."
      />
      <button
        className="w-fit rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
        onClick={() => createMutation.mutate(text)}
        disabled={!text.trim() || createMutation.isPending}
      >
        抽取
      </button>
      {terminal === null && runId ? <p>流式中... {events.length} chunks</p> : null}
      {terminal === "failed" ? (
        <p className="text-red-600" role="alert">
          抽取失败
        </p>
      ) : null}
      {pending ? (
        <section className="border p-3">
          <h2 className="font-semibold">草稿</h2>
          <ul>
            {pending.content.facts.map((fact, index) => (
              <li key={`${fact.claim}-${index}`}>{fact.claim}</li>
            ))}
          </ul>
          <button
            className="mt-2 rounded bg-green-600 px-3 py-1 text-white disabled:opacity-50"
            onClick={() => approveMutation.mutate(pending.id)}
            disabled={approveMutation.isPending}
          >
            批准发布
          </button>
        </section>
      ) : null}
    </div>
  );
}
