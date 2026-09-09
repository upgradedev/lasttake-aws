import {copyFile} from 'node:fs/promises';
for (const name of ['UAT.testbook.html','UAT.testbook.json']) await copyFile(name,`dist/${name}`);
