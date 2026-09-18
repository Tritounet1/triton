import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LogsSettings } from "./LogsSettings";

function jsonResponse(body: unknown, ok = true) {
  return Promise.resolve({ ok, json: () => Promise.resolve(body) } as Response);
}

const summary = {
  month: "2026-09",
  total_calls: 42,
  total_tokens: 123456,
  total_cost_usd: 4.21,
  by_model: [
    {
      model: "anthropic/claude-sonnet",
      calls: 30,
      total_tokens: 100000,
      cost_usd: 3.5,
    },
    {
      model: "openai/gpt",
      calls: 12,
      total_tokens: 23456,
      cost_usd: 0.71,
    },
  ],
  by_project: [
    {
      project_id: "project-1",
      project_name: "Triton",
      calls: 35,
      total_tokens: 110000,
      cost_usd: 4,
    },
    {
      project_id: null,
      project_name: "Sans projet",
      calls: 7,
      total_tokens: 13456,
      cost_usd: 0.21,
    },
  ],
  by_day: [
    { date: "2026-09-18", calls: 42, total_tokens: 123456, cost_usd: 4.21 },
  ],
};

function mockFetch() {
  return vi.fn((input: string | URL | Request) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.endsWith("/logs/cost_summary")) return jsonResponse(summary);
    if (url.endsWith("/settings/budget/status")) {
      return jsonResponse({ monthly_budget_usd: 10, spent_usd: 4.21, exceeded: false });
    }
    if (url.endsWith("/logs")) {
      // Deliberately much smaller than the monthly summary: this proves the
      // headline dashboard no longer derives from the 500-row raw log window.
      return jsonResponse([
        {
          type: "model_call",
          timestamp: "2026-09-18T10:00:00",
          model: "anthropic/claude-sonnet",
          prompt_tokens: 6,
          completion_tokens: 4,
          total_tokens: 10,
          tool_calls: 0,
          duration_seconds: 1,
          cost_usd: 0.01,
        },
      ]);
    }
    return jsonResponse(null, false);
  });
}

describe("LogsSettings", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the complete monthly summary and its model/project breakdowns", async () => {
    render(<LogsSettings />);

    expect(await screen.findByText("Répartition mensuelle par modèle")).toBeInTheDocument();
    expect(screen.getByText("Répartition mensuelle par projet")).toBeInTheDocument();
    expect(screen.getAllByText("anthropic/claude-sonnet")).not.toHaveLength(0);
    expect(screen.getByText("Triton")).toBeInTheDocument();
    expect(screen.getByText("Sans projet")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getAllByText("$4.21")).not.toHaveLength(0);
    expect(
      screen.getAllByText((content) => content.replace(/\D/g, "") === "123456"),
    ).not.toHaveLength(0);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/logs/cost_summary");
    });
  });
});
