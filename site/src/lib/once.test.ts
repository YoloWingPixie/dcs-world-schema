import { describe, expect, it } from "vitest";
import { once, settled } from "./once";

describe("once", () => {
  it("shares one promise per key and remembers its resolved value", async () => {
    let calls = 0;
    const load = () => once("test:value", async () => ++calls);
    const first = load();
    expect(load()).toBe(first);
    expect(settled<number>("test:value")).toBeUndefined();
    await first;
    expect(settled<number>("test:value")).toBe(1);
    expect(await load()).toBe(1);
    expect(calls).toBe(1);
  });

  it("records no failure, so the next call retries", async () => {
    let calls = 0;
    const load = () =>
      once("test:retry", async () => {
        calls++;
        if (calls === 1) throw new Error("down");
        return "up";
      });
    await expect(load()).rejects.toThrow("down");
    expect(settled<string>("test:retry")).toBeUndefined();
    expect(await load()).toBe("up");
    expect(settled<string>("test:retry")).toBe("up");
    expect(calls).toBe(2);
  });

  it("knows nothing of keys never asked", () => {
    expect(settled("test:never")).toBeUndefined();
  });
});
