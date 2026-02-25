/**
 * TASK-095 Phase 5: Generate a manager login token.
 *
 * Usage: npx tsx scripts/create-manager.ts "Manager Name"
 *
 * Creates a manager entry in the DB and prints the login token.
 * The token is shown once — save it securely.
 */

import crypto from 'crypto';
import initSqlJs from 'sql.js';
import fs from 'fs';
import path from 'path';

const DB_PATH = path.join(process.cwd(), 'data', 'lounge.db');

async function main() {
  const name = process.argv[2];
  if (!name) {
    console.error('Usage: npx tsx scripts/create-manager.ts "Manager Name"');
    process.exit(1);
  }

  const SQL = await initSqlJs();
  const dir = path.dirname(DB_PATH);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }

  let db;
  if (fs.existsSync(DB_PATH)) {
    const buffer = fs.readFileSync(DB_PATH);
    db = new SQL.Database(buffer);
  } else {
    db = new SQL.Database();
  }

  // Ensure table exists
  db.run(`
    CREATE TABLE IF NOT EXISTS managers (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      token TEXT UNIQUE NOT NULL,
      created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
  `);

  const id = crypto.randomUUID();
  const token = `mgr-${crypto.randomBytes(32).toString('hex')}`;

  db.run('INSERT INTO managers (id, name, token) VALUES (?, ?, ?)', [id, name, token]);

  // Save
  const data = db.export();
  fs.writeFileSync(DB_PATH, Buffer.from(data));
  db.close();

  console.log('');
  console.log('Manager created successfully.');
  console.log(`  Name:  ${name}`);
  console.log(`  ID:    ${id}`);
  console.log(`  Token: ${token}`);
  console.log('');
  console.log('Save this token — it will not be shown again.');
  console.log('Use it to log in at alive.kaikk.jp/login');
}

main().catch(console.error);
