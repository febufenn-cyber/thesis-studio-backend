// pm2 ecosystem config for thesis-studio-backend.
//
// Wraps uvicorn in scripts/run_thesis_api.sh so a per-process virtual-memory
// cap (`ulimit -v`) is enforced — bounds runaway memory in the uvicorn process
// and any `claude -p` subprocess it spawns. Without that cap, a leaky claude
// invocation could push a 1GB-RAM VM into OOM and take down the LeadFinder
// processes that share the host.
//
// max_memory_restart is pm2's graceful-restart threshold (RSS-based). It and
// the ulimit serve different purposes: ulimit is a hard allocation cap;
// max_memory_restart is a soft "you've grown too big, recycle yourself" line.

module.exports = {
  apps: [
    {
      name: 'thesis-api',
      script: '/opt/thesis-studio-backend/scripts/run_thesis_api.sh',
      cwd: '/opt/thesis-studio-backend',
      interpreter: 'none',
      max_memory_restart: '600M',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      kill_timeout: 8000,
    },
  ],
};
