import { spawn } from 'node:child_process';
const backend = spawn(process.execPath, ['server/index.mjs'], {
  stdio: 'inherit',
  env: { ...process.env, PORT: '5181' },
});
const frontend = spawn(process.execPath, ['node_modules/vite/bin/vite.js'], {
  stdio: 'inherit',
});
function stop() {
  backend.kill('SIGTERM');
  frontend.kill('SIGTERM');
}
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
backend.on('exit', (code) => {
  frontend.kill();
  process.exitCode = code || 0;
});
frontend.on('exit', (code) => {
  backend.kill();
  process.exitCode = code || 0;
});
