// PM2 ecosystem for Robofox Thesis Studio.
//
// The API stays responsive while one dedicated worker serialises manuscript
// ingestion and LibreOffice conversions on the small shared Oracle VM.

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
    {
      name: 'thesis-worker',
      script: '/opt/thesis-studio-backend/venv/bin/python',
      args: '-m app.services.job_queue',
      cwd: '/opt/thesis-studio-backend',
      interpreter: 'none',
      max_memory_restart: '650M',
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      kill_timeout: 15000,
      env: {
        PYTHONPATH: '/opt/thesis-studio-backend',
      },
    },
  ],
};
