"use client";

import { useEffect, useMemo, useState } from "react";

import {
  JobStatusResp,
  Voice,
  deleteJob,
  listModels,
  listVoices,
  pollJob,
  submitJob,
} from "@/lib/api";

type ViewState =
  | { kind: "form" }
  | { kind: "submitting" }
  | { kind: "running"; jobId: string; status: JobStatusResp }
  | { kind: "done"; jobId: string; status: JobStatusResp }
  | { kind: "failed"; jobId: string; status: JobStatusResp };

export default function Page() {
  const [text, setText] = useState("");
  const [voice, setVoice] = useState("");
  const [face, setFace] = useState<File | null>(null);
  const [paramsJson, setParamsJson] = useState("");
  const [voices, setVoices] = useState<Voice[] | null>(null);
  const [modelsActive, setModelsActive] = useState<string>("");
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);
  const [view, setView] = useState<ViewState>({ kind: "form" });

  useEffect(() => {
    (async () => {
      try {
        const [vs, m] = await Promise.all([listVoices(), listModels()]);
        setVoices(vs);
        setModelsActive(`${m.tts.active} + ${m.lipsync.active}`);
        if (vs.length && !voice) setVoice(vs[0].voice_id);
      } catch (e) {
        setBootstrapError((e as Error).message);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const canSubmit = useMemo(
    () => view.kind === "form" && text.trim() && voice && face,
    [view.kind, text, voice, face],
  );

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!face || !voice || !text.trim()) return;
    let params: Record<string, unknown> | undefined;
    if (paramsJson.trim()) {
      try {
        params = JSON.parse(paramsJson);
      } catch (err) {
        alert(`Invalid params JSON: ${(err as Error).message}`);
        return;
      }
    }
    setView({ kind: "submitting" });
    try {
      const created = await submitJob({ text, voice, face, params });
      startPolling(created.job_id);
    } catch (err) {
      alert((err as Error).message);
      setView({ kind: "form" });
    }
  }

  function startPolling(jobId: string) {
    setView({
      kind: "running",
      jobId,
      status: {
        job_id: jobId,
        status: "queued",
        stage: null,
        progress: 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        preview_url: `/api/v1/jobs/${jobId}/preview`,
        download_url: `/api/v1/jobs/${jobId}/download`,
        error: null,
      },
    });
    pollJob(jobId, (s) => {
      if (s.status === "done") setView({ kind: "done", jobId, status: s });
      else if (s.status === "failed") setView({ kind: "failed", jobId, status: s });
      else setView({ kind: "running", jobId, status: s });
    });
  }

  async function onReset() {
    if (view.kind === "done" || view.kind === "failed") {
      try {
        await deleteJob(view.jobId);
      } catch {
        /* best-effort */
      }
    }
    setView({ kind: "form" });
    setText("");
    setFace(null);
    setParamsJson("");
  }

  return (
    <div className="container">
      <h1>Lip-Sync Studio</h1>
      <p className="subtitle">
        Text + face → lip-synced video.
        {modelsActive && <span className="muted"> · active: {modelsActive}</span>}
      </p>

      {bootstrapError && (
        <div className="error-box" style={{ marginBottom: 16 }}>
          Failed to load voices/models: {bootstrapError}
        </div>
      )}

      {(view.kind === "form" || view.kind === "submitting") && (
        <form className="card" onSubmit={onSubmit}>
          <div className="field">
            <label htmlFor="text">Text</label>
            <textarea
              id="text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Enter the script to speak…"
              disabled={view.kind !== "form"}
            />
          </div>

          <div className="field">
            <label htmlFor="voice">Voice</label>
            <select
              id="voice"
              value={voice}
              onChange={(e) => setVoice(e.target.value)}
              disabled={!voices || view.kind !== "form"}
            >
              {!voices && <option value="">loading…</option>}
              {voices?.map((v) => (
                <option key={v.voice_id} value={v.voice_id}>
                  {v.name} ({v.language_code}
                  {v.gender ? `, ${v.gender}` : ""})
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label htmlFor="face">Face (image or short video)</label>
            <input
              id="face"
              type="file"
              accept="image/jpeg,image/png,video/mp4"
              onChange={(e) => setFace(e.target.files?.[0] ?? null)}
              disabled={view.kind !== "form"}
            />
          </div>

          <div className="field">
            <label htmlFor="params">Advanced params (JSON, optional)</label>
            <input
              id="params"
              type="text"
              value={paramsJson}
              onChange={(e) => setParamsJson(e.target.value)}
              placeholder='{"bbox_shift":5,"extra_margin":10}'
              disabled={view.kind !== "form"}
            />
          </div>

          <div className="actions">
            <button className="primary" type="submit" disabled={!canSubmit}>
              {view.kind === "submitting" ? "Submitting…" : "Generate"}
            </button>
          </div>
        </form>
      )}

      {(view.kind === "running" || view.kind === "done" || view.kind === "failed") && (
        <JobCard view={view} onReset={onReset} />
      )}
    </div>
  );
}

function JobCard({
  view,
  onReset,
}: {
  view: Extract<ViewState, { kind: "running" | "done" | "failed" }>;
  onReset: () => void;
}) {
  const { status, jobId } = view;
  const label = view.kind === "running"
    ? stageLabel(status.stage) || status.status
    : view.kind;

  return (
    <div className="card">
      <div className="progress" style={{ marginBottom: 12 }}>
        <span className={`dot ${view.kind}`} />
        <span>{label}</span>
        <div className="bar" aria-hidden>
          <div style={{ width: `${status.progress}%` }} />
        </div>
      </div>

      <div className="muted" style={{ marginBottom: 12 }}>
        job {jobId}
      </div>

      {view.kind === "failed" && status.error && (
        <div className="error-box">{status.error}</div>
      )}

      {view.kind === "done" && (
        <>
          <video src={status.preview_url} controls autoPlay playsInline />
          <div className="row">
            <a className="primary" href={status.download_url} download style={{ textDecoration: "none", padding: "10px 20px", borderRadius: 6, background: "var(--accent)", color: "#fff" }}>
              Download MP4
            </a>
            <button className="ghost" onClick={onReset}>New video</button>
          </div>
        </>
      )}

      {view.kind === "failed" && (
        <div className="actions" style={{ marginTop: 12 }}>
          <button className="ghost" onClick={onReset}>Try again</button>
        </div>
      )}
    </div>
  );
}

function stageLabel(stage: JobStatusResp["stage"]): string {
  switch (stage) {
    case "tts": return "generating audio…";
    case "lipsync": return "generating video…";
    case "done": return "done";
    default: return "queued";
  }
}
