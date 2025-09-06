require("./observe");

const express = require("express");
const morgan = require("morgan");
const app = express();
const PORT = 3001;

// Morgan tokens for trace context
morgan.token('trace-id', (req) => {
  const { trace } = require('@opentelemetry/api');
  const span = trace.getActiveSpan();
  return span ? span.spanContext().traceId : 'no-trace';
});

morgan.token('span-id', (req) => {
  const { trace } = require('@opentelemetry/api');
  const span = trace.getActiveSpan();
  return span ? span.spanContext().spanId : 'no-span';
});

const customFormat = ':method :url :status :res[content-length] - :response-time ms [trace: :trace-id] [span: :span-id]';

// Custom stream that sends to backend only
const backendStream = {
  write: (message) => {
    fetch('http://localhost:8000/v1/logs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        timestamp: new Date().toISOString(),
        level: 'info',
        message: message.trim(),
        source: 'morgan'
      })
    }).catch(() => {}); // Silent fail
  }
};

app.use(morgan(customFormat, { stream: backendStream }));

app.get("/", (req, res) => {
  res.send("Client app running");
});

app.get("/boom", (req, res) => {
  throw new Error("Something went wrong");
});

app.get("/test", (req, res) => {
  res.json({ 
    message: "Test endpoint", 
    timestamp: new Date().toISOString()
  });
});

app.listen(PORT);