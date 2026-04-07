import express from 'express';
import cors from 'cors';
import fetch from 'node-fetch';
import dotenv from 'dotenv';
import { Database } from 'arangojs';
import {
  Connection,
  PublicKey,
  clusterApiUrl
} from '@solana/web3.js';

dotenv.config();

const RAG_URL = process.env.RAG_URL || 'http://localhost:8000';
const RAG_TIMEOUT_MS = Number(process.env.RAG_TIMEOUT_MS || 10000);

function buildUnverifiedFallback(reason, model = 'mistral:latest') {
  return {
    answer: 'Unable to generate an answer from Ollama.',
    sources: [],
    confidence: 0.0,
    confidence_label: 'low',
    escalate: true,
    escalation_reason: reason,
    user_can_escalate: true,
    model,
    status: 'degraded_fallback',
    verified: false,
    verification_status: 'unverified',
    llm_available: false,
    should_retry: true,
    error: reason
  };
}

function normalizeRagPayload(payload = {}) {
  const isVerified = payload.verified ?? !Boolean(payload.escalate);
  return {
    answer: payload.answer ?? 'No response generated.',
    sources: Array.isArray(payload.sources) ? payload.sources : [],
    confidence: Number.isFinite(payload.confidence) ? payload.confidence : 0.0,
    confidence_label: payload.confidence_label ?? 'low',
    escalate: Boolean(payload.escalate),
    escalation_reason: payload.escalation_reason ?? '',
    user_can_escalate: payload.user_can_escalate ?? true,
    model: payload.model ?? 'mistral:latest',
    status: payload.status ?? 'ok',
    verified: Boolean(isVerified),
    verification_status: payload.verification_status ?? (isVerified ? 'verified' : 'unverified'),
    llm_available: payload.llm_available ?? true,
    should_retry: payload.should_retry ?? false,
    error: payload.error ?? '',
    query: payload.query,
    tier: payload.tier,
    region_id: payload.region_id,
    session_id: payload.session_id,
    resumed: payload.resumed,
  };
}

const app = express();
app.use(cors());
app.use(express.json());

// ==========================
// ArangoDB Setup
// ==========================
const db = new Database({
  url: process.env.ARANGO_URL,
  databaseName: process.env.ARANGO_DB,
  auth: {
    username: process.env.ARANGO_USER,
    password: process.env.ARANGO_PASSWORD
  }
});

// ==========================
// Solana Setup
// ==========================
const connection = new Connection(clusterApiUrl('devnet'), 'confirmed');

// ==========================
// Health Check
// ==========================
app.get('/', (req, res) => {
  res.json({ status: 'API running' });
});

// ==========================
// Example: Get data from ArangoDB
// ==========================
app.get('/batch/:id', async (req, res) => {
  try {
    const cursor = await db.query(`
      FOR doc IN batches
      FILTER doc.batchId == @id
      RETURN doc
    `, { id: req.params.id });

    const result = await cursor.all();
    res.json(result[0] || null);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'DB query failed' });
  }
});

// ==========================
// RAG + Verification Endpoint
// ==========================
app.get('/verify/:id', async (req, res) => {
  try {
    const batchId = req.params.id;

    // 1. Get batch data from ArangoDB
    const cursor = await db.query(`
      FOR doc IN batches
      FILTER doc.batchId == @id
      RETURN doc
    `, { id: batchId });

    const batch = (await cursor.all())[0];

    if (!batch) {
      return res.status(404).json({ error: 'Batch not found' });
    }

    // 2. Call LangChain RAG service (Python)
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), RAG_TIMEOUT_MS);

    let ragData;
    try {
      const ragResponse = await fetch(`${RAG_URL}/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ batch }),
        signal: controller.signal
      });

      if (!ragResponse.ok) {
        ragData = buildUnverifiedFallback(`LLM unavailable: upstream ${ragResponse.status}`);
      } else {
        ragData = normalizeRagPayload(await ragResponse.json());
      }
    } catch (err) {
      const reason = err?.name === 'AbortError'
        ? 'LLM unavailable: timeout'
        : `LLM unavailable: ${err?.message || 'unknown error'}`;
      ragData = buildUnverifiedFallback(reason);
    } finally {
      clearTimeout(timeout);
    }

    // 3. (Optional) Prepare hash / metadata for Solana
    const verificationHash = Buffer.from(
      JSON.stringify(ragData)
    ).toString('base64');

    res.json({
      batch,
      rag: ragData,
      hash: verificationHash
    });

  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Verification failed' });
  }
});

// ==========================
// Example: Check Solana Account
// ==========================
app.get('/solana/:address', async (req, res) => {
  try {
    const pubkey = new PublicKey(req.params.address);
    const balance = await connection.getBalance(pubkey);

    res.json({
      address: pubkey.toBase58(),
      balance: balance / 1e9
    });
  } catch (err) {
    console.error(err);
    res.status(400).json({ error: 'Invalid Solana address' });
  }
});

// ==========================
// Start Server
// ==========================
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Node API running on port ${PORT}`);
});