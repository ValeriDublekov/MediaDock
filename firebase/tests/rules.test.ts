import {
  assertFails,
  assertSucceeds,
  initializeTestEnvironment,
  RulesTestEnvironment,
} from "@firebase/rules-unit-testing";
import { afterAll, beforeAll, beforeEach, describe, it } from "vitest";
import { readFileSync } from "fs";
import { resolve } from "path";

let testEnv: RulesTestEnvironment;

beforeAll(async () => {
  const rules = readFileSync(resolve(__dirname, "../../firestore.rules"), "utf8");
  testEnv = await initializeTestEnvironment({
    projectId: "demo-moviesfeed-rules",
    firestore: {
      rules,
      host: "127.0.0.1",
      port: 8888,
    },
  });
});

beforeEach(async () => {
  await testEnv.clearFirestore();
});

afterAll(async () => {
  await testEnv.cleanup();
});

describe("MoviesFeed Firestore Rules", () => {
  const unauthDb = () => testEnv.unauthenticatedContext().firestore();
  
  const authNoAllowlistDb = () => testEnv.authenticatedContext("user-123", {
    email: "user@example.com"
  }).firestore();
  
  const setupAllowlistedUser = async (uid: string, email: string) => {
    await testEnv.withSecurityRulesDisabled(async (context) => {
      const db = context.firestore();
      await db.collection("allowlist").doc(uid).set({
        enabled: true,
        email,
      });
    });
    return testEnv.authenticatedContext(uid, { email }).firestore();
  };

  const setupDisabledUser = async (uid: string, email: string) => {
    await testEnv.withSecurityRulesDisabled(async (context) => {
      const db = context.firestore();
      await db.collection("allowlist").doc(uid).set({
        enabled: false,
        email,
      });
    });
    return testEnv.authenticatedContext(uid, { email }).firestore();
  };

  describe("Unauthenticated access", () => {
    it("denies catalog read", async () => {
      await assertFails(unauthDb().collection("titles").doc("tt123").get());
    });
    
    it("denies allowlist read", async () => {
      await assertFails(unauthDb().collection("allowlist").doc("user-123").get());
    });
  });

  describe("Authenticated non-allowlisted denial", () => {
    it("denies catalog read", async () => {
      const db = authNoAllowlistDb();
      await assertFails(db.collection("titles").doc("tt123").get());
    });
    
    it("denies disabled user catalog read", async () => {
      const db = await setupDisabledUser("user-123", "user@example.com");
      await assertFails(db.collection("titles").doc("tt123").get());
    });
  });

  describe("Allowlisted catalog read", () => {
    it("allows reading titles and occurrences", async () => {
      const db = await setupAllowlistedUser("user-456", "admin@example.com");
      await assertSucceeds(db.collection("titles").doc("tt123").get());
      await assertSucceeds(db.collection("titles").doc("tt123").collection("occurrences").doc("occ1").get());
    });

    it("allows reading own allowlist doc", async () => {
      const db = await setupAllowlistedUser("user-456", "admin@example.com");
      await assertSucceeds(db.collection("allowlist").doc("user-456").get());
    });
    
    it("denies reading other allowlist doc", async () => {
      const db = await setupAllowlistedUser("user-456", "admin@example.com");
      await assertFails(db.collection("allowlist").doc("user-other").get());
    });
  });

  describe("Client writes denied (catalog/cache/scan)", () => {
    it("denies write to titles", async () => {
      const db = await setupAllowlistedUser("user-456", "admin@example.com");
      await assertFails(db.collection("titles").doc("tt123").set({ title: "Hack" }));
      await assertFails(db.collection("titles").doc("tt123").collection("occurrences").doc("occ1").set({ rawTitle: "Hack" }));
    });
    
    it("denies write to omdbCache", async () => {
      const db = await setupAllowlistedUser("user-456", "admin@example.com");
      await assertFails(db.collection("omdbCache").doc("key1").set({ status: "found" }));
    });
    
    it("denies write to scanRuns", async () => {
      const db = await setupAllowlistedUser("user-456", "admin@example.com");
      await assertFails(db.collection("scanRuns").doc("run1").set({ status: "running" }));
    });
  });

  describe("Reserved users/{uid} namespace", () => {
    it("denies read and write for now", async () => {
      const db = await setupAllowlistedUser("user-456", "admin@example.com");
      // Even the owner is denied until concrete schema is added
      await assertFails(db.collection("users").doc("user-456").collection("watchlist").doc("tt123").set({ added: true }));
      await assertFails(db.collection("users").doc("user-456").collection("watchlist").doc("tt123").get());
      
      // Other users
      await assertFails(db.collection("users").doc("user-other").collection("watchlist").doc("tt123").get());
    });
  });
});
