import { useEffect, useRef, useState } from 'react';
import { clipsApi } from './api';

// Polls a stage job every 2s until it reaches done|error. Same contract as the
// explainer lane's hook. `onFinish(job)` fires once when it settles.
export default function useClipsJob(onFinish) {
  const [job, setJob] = useState(null);
  const timer = useRef(null);
  const finishRef = useRef(onFinish);
  finishRef.current = onFinish;

  const stop = () => {
    if (timer.current) { clearInterval(timer.current); timer.current = null; }
  };

  const start = async (starter) => {
    stop();
    setJob({ status: 'queued', progress: 0, logs: [] });
    let jobId;
    try {
      const res = await starter(); // returns { job_id }
      jobId = res.job_id;
    } catch (e) {
      setJob({ status: 'error', error: e.message, logs: [e.message] });
      return;
    }
    timer.current = setInterval(async () => {
      try {
        const j = await clipsApi.job(jobId);
        setJob(j);
        if (j.status === 'done' || j.status === 'error') {
          stop();
          finishRef.current?.(j);
        }
      } catch {
        /* transient — keep polling */
      }
    }, 2000);
  };

  useEffect(() => stop, []);

  return {
    job,
    start,
    clear: () => { stop(); setJob(null); },
    running: !!timer.current || (job && (job.status === 'queued' || job.status === 'running')),
  };
}
