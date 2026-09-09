import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

export function checkAudit(full, runtime) {
  for (const [name, report] of [['full', full], ['runtime', runtime]]) {
    const counts = report?.metadata?.vulnerabilities;
    if (report?.error || report?.auditReportVersion !== 2 || !report?.vulnerabilities ||
        !counts || !['info', 'low', 'moderate', 'high', 'critical', 'total'].every(
          key => Number.isInteger(counts[key]) && counts[key] >= 0)) {
      throw new Error(`${name} audit unavailable or malformed; refusing to treat it as clean.`);
    }
    console.log(`${name} audit: ${JSON.stringify(counts)}`);
  }
  if (runtime.metadata.vulnerabilities.total !== 0 || Object.keys(runtime.vulnerabilities).length !== 0) {
    throw new Error('Runtime audit requires zero vulnerabilities, including low severity.');
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  checkAudit(...process.argv.slice(2).map(path => JSON.parse(readFileSync(path, 'utf8'))));
}
