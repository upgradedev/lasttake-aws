import {copyFile} from 'node:fs/promises';
for (const name of ['UAT.testbook.html','UAT.testbook.json']) await copyFile(name,`dist/${name}`);
// The required architecture diagram is one file, docs/architecture.svg, kept
// beside the README so the repository and the deployed page show the same
// picture. The Architecture page embeds this copy; nothing is redrawn in JSX.
await copyFile('../docs/architecture.svg','dist/architecture.svg');
