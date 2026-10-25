import { randomUUID } from 'node:crypto';
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { query } from '@anthropic-ai/claude-agent-sdk';

const stateFile = process.argv[2];
if (!stateFile || !path.isAbsolute(stateFile)) {
  console.error('Usage: collect.mjs ABSOLUTE_STATE_FILE');
  process.exit(2);
}

const stopInput = new AbortController();
async function* noPrompts() {
  await new Promise((resolve) => {
    stopInput.signal.addEventListener('abort', resolve, { once: true });
  });
}

function windowData(source, durationMinutes) {
  if (!source || source.utilization == null) return null;
  const usedPercent = Number(source.utilization);
  if (!Number.isFinite(usedPercent) || usedPercent < 0 || usedPercent > 100) {
    throw new Error('Claude returned an invalid usage percentage');
  }
  return {
    duration_minutes: durationMinutes,
    used_percent: usedPercent,
    resets_at: source.resets_at ?? null,
  };
}

const session = query({
  prompt: noPrompts(),
  options: {
    cwd: os.tmpdir(),
    settingSources: [],
    permissionMode: 'dontAsk',
    tools: [],
    mcpServers: {},
  },
});

let timeout;
try {
  const usage = await Promise.race([
    session.usage_EXPERIMENTAL_MAY_CHANGE_DO_NOT_RELY_ON_THIS_API_YET({
      skipBehaviors: true,
    }),
    new Promise((_, reject) => {
      timeout = setTimeout(() => reject(new Error('Claude usage request timed out')), 30000);
    }),
  ]);
  if (!usage.rate_limits_available || !usage.rate_limits) {
    throw new Error('Claude plan rate limits are unavailable for this sign-in');
  }

  const fiveHour = windowData(usage.rate_limits.five_hour, 300);
  const weekly = windowData(usage.rate_limits.seven_day, 10080);
  if (!fiveHour && !weekly) {
    throw new Error('Claude returned no five-hour or weekly usage window');
  }

  const snapshot = {
    observed_at: new Date().toISOString(),
    source: 'claude-agent-sdk-usage',
    five_hour: fiveHour,
    weekly,
  };
  await fs.mkdir(path.dirname(stateFile), { recursive: true });
  const temporaryFile = `${stateFile}.${process.pid}.${randomUUID()}.tmp`;
  try {
    await fs.writeFile(temporaryFile, JSON.stringify(snapshot), { mode: 0o600, flag: 'wx' });
    await fs.rename(temporaryFile, stateFile);
  } finally {
    await fs.rm(temporaryFile, { force: true });
  }
  console.log(`Claude usage collected: ${fiveHour ? '5h' : ''} ${weekly ? 'weekly' : ''}`.trim());
} catch (error) {
  console.error(`Claude usage collection failed: ${error.message}`);
  process.exitCode = 1;
} finally {
  clearTimeout(timeout);
  stopInput.abort();
  session.close();
}
