# Selected prompts

1. IRSA's TAP/SIA service is down (confirmed 502/proxy errors). SPHEREx data is also
   available directly via public S3: bucket "nasa-irsa-spherex", region us-east-1,
   no credentials needed (anonymous/unsigned requests). Browsable at
   https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/index.html
   Switch Phase 0 to use S3 directly instead of TAP: browse/list the bucket with
   s3fs or boto3 (anon=True / unsigned config) to find SPHEREx exposure files
   covering WISE 0855's position, using the file naming convention from
   SPEC.md (level2/[Planning Period]/l2b-v[Version]-[ProcessingDate]/[Detector]/).
   You may need to list directories and filter by filename/WCS rather than a
   spatial TAP query, since there's no query service on S3 - read the files'
   headers to check sky coverage. Try this now; report back whether S3 access
   works before building further on this approach.

2. Move into Phase 3 now. Do A (Candidates) first, then C (Truth check), in that
    order - skip B and D entirely unless both A and C are solid with over an hour
    of build time still left.
    For the truth-check (C), note: Gaia DR3 can't be queried live right now
    (IRSA's query services are still down). Use literature proper motions for
    whatever comparison stars you pick, clearly labeled as literature values, not
    live Gaia queries - same caveat as the target positions already in PROGRESS.md.
    Let the coverage daemon keep running in the background as before - don't wait
    on it. Build against whatever's in the cache right now; your export script
    can pick up more later.
    Timebox: if 3A isn't producing real flagged candidates within 45 minutes,
    stop, commit what you have (even if incomplete), and move to 3C. Report back
    when both are done or when you hit the timebox.
