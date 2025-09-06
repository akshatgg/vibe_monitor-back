const { NodeSDK } = require("@opentelemetry/sdk-node");
const { getNodeAutoInstrumentations } = require("@opentelemetry/auto-instrumentations-node");
const { OTLPTraceExporter } = require("@opentelemetry/exporter-trace-otlp-http");
const { OTLPMetricExporter } = require("@opentelemetry/exporter-metrics-otlp-http");
const { PeriodicExportingMetricReader } = require("@opentelemetry/sdk-metrics");

// --- Trace Exporter ---
const otelTraceExporter = new OTLPTraceExporter({
  url: "http://localhost:8000/v1/traces",
});

// --- Metric Exporter ---
const otelMetricExporter = new OTLPMetricExporter({
  url: "http://localhost:8000/v1/metrics",
});

const metricReader = new PeriodicExportingMetricReader({
  exporter: otelMetricExporter,
  exportIntervalMillis: 50000,
});

// --- SDK Configuration ---
const sdk = new NodeSDK({
  traceExporter: otelTraceExporter,
  metricReader,
  instrumentations: [getNodeAutoInstrumentations()],
});

// Start SDK
sdk.start();

console.log("✅ OpenTelemetry SDK started");
console.log("📊 Metrics export interval: 5 seconds");
console.log("🔍 Traces will be sent to: http://localhost:8000/v1/traces");
console.log("📈 Metrics will be sent to: http://localhost:8000/v1/metrics");