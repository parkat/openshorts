"""Clips lane — mine ONE long-form video for many self-contained Shorts.

Source-first, where the explainer lane is script-first: instead of writing a script
and hunting footage to illustrate it, this takes a long video and finds the moments
inside it that already stand alone, then cuts and renders each as a 9:16 Short in
the speaker's own voice.

Stages (each idempotent, each resumable — see clips/cli.py):

    ingest   URL -> one cached full download + a timed transcript
    moments  transcript -> N candidate windows (title/hook/why/score), LLM
    cut      candidate -> speech-snapped 16:9 clip + master audio + word captions
    render   clip + captions -> 9:16 MP4 via the Remotion render-service

State lives in SQLite (`store.ClipSource` / `store.ClipCandidate`) so the queue
survives restarts, exactly like the explainer lane.
"""
