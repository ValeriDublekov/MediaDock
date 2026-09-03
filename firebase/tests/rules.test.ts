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
        role: "reader",
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
        role: "reader",
      });
    });
    return testEnv.authenticatedContext(uid, { email }).firestore();
  };

  const setupAdminUser = async (uid: string, email: string) => {
    await testEnv.withSecurityRulesDisabled(async (context) => {
      const db = context.firestore();
      await db.collection("allowlist").doc(uid).set({
        enabled: true,
        email,
        role: "admin",
      });
    });
    return testEnv.authenticatedContext(uid, { email }).firestore();
  };

  describe("Unauthenticated access", () => {
    it("denies catalog read", async () => {
      await assertFails(unauthDb().collection("titles").doc("tt123").get());
    });

    it("denies settings and manual-mapping writes", async () => {
      await assertFails(unauthDb().collection("titles").doc("settings_config").set({
        updatedBy: "anonymous",
      }));
      await assertFails(unauthDb().collection("manualMappings").doc("mapping-1").set({
        rawTitle: "The Matrix",
        imdbId: "tt0133093",
        createdAt: new Date(),
        createdBy: "anonymous",
      }));
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

    it("denies disabled user settings and manual-mapping writes", async () => {
      const db = await setupDisabledUser("user-123", "user@example.com");
      await assertFails(db.collection("titles").doc("settings_config").set({
        updatedBy: "user-123",
      }));
      await assertFails(db.collection("manualMappings").doc("mapping-1").set({
        rawTitle: "The Matrix",
        imdbId: "tt0133093",
        createdAt: new Date(),
        createdBy: "user-123",
      }));
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

    it("allows reading RSS snapshot generations and the current pointer", async () => {
      const db = await setupAllowlistedUser("user-456", "admin@example.com");
      await assertSucceeds(db.collection("rssSnapshots").doc("snapshot-1").get());
      await assertSucceeds(
        db.collection("rssSnapshots").doc("snapshot-1").collection("items").doc("tt123").get()
      );
      await assertSucceeds(db.collection("rssSnapshotState").doc("current").get());
    });
  });

  describe("Client writes denied (catalog/cache/scan)", () => {
    it("denies catalog and settings writes for a reader", async () => {
      const db = await setupAllowlistedUser("user-456", "admin@example.com");
      await assertFails(db.collection("titles").doc("tt123").set({ title: "Hack" }));
      await assertFails(db.collection("titles").doc("settings_config").set({
        rssFeeds: {},
        excludedGenres: [],
        excludedCountries: [],
        minMovieRating: 0,
        minSeriesRating: 0,
        minImdbVotes: 0,
        updatedBy: "user-456",
      }));
      await assertFails(db.collection("titles").doc("tt123").collection("occurrences").doc("occ1").set({ rawTitle: "Hack" }));
    });

    it("denies RSS snapshot writes for an allowlisted reader", async () => {
      const db = await setupAllowlistedUser("user-456", "admin@example.com");
      await assertFails(db.collection("rssSnapshots").doc("snapshot-1").set({ status: "ready" }));
      await assertFails(
        db.collection("rssSnapshots").doc("snapshot-1").collection("items").doc("tt123").set({
          titleId: "tt123",
          rssPosition: 0,
        })
      );
      await assertFails(db.collection("rssSnapshotState").doc("current").set({ snapshotId: "snapshot-1" }));
    });

    it("denies browser settings writes for an admin", async () => {
      const db = await setupAdminUser("admin-456", "admin@example.com");
      await assertFails(db.collection("titles").doc("settings_config").set({
        rssFeeds: {
          movies: { url: "https://feed.example.test/movies.atom", type: "movie" },
        },
        excludedGenres: ["Horror"],
        excludedCountries: ["India"],
        minMovieRating: 6.5,
        minSeriesRating: 7,
        minImdbVotes: 0,
        updatedBy: "admin-456",
      }));
    });

    const validAdminSettings = () => ({
      rssFeeds: {
        movies: { url: "https://feed.example.test/movies.atom", type: "movie" },
      },
      excludedGenres: ["Horror"],
      excludedCountries: ["India"],
      minMovieRating: 6.5,
      minSeriesRating: 7,
      minImdbVotes: 0,
      updatedBy: "admin-456",
    });

    it("rejects feeds missing a URL or type", async () => {
      const db = await setupAdminUser("admin-456", "admin@example.com");
      const valid = validAdminSettings();
      await assertFails(db.collection("titles").doc("settings_config").set({
        ...valid,
        rssFeeds: { movies: { type: "movie" } },
      }));
      await assertFails(db.collection("titles").doc("settings_config").set({
        ...valid,
        rssFeeds: { movies: { url: "https://feed.example.test/movies.atom" } },
      }));
    });

    it("rejects a feed with an extra nested field", async () => {
      const db = await setupAdminUser("admin-456", "admin@example.com");
      const valid = validAdminSettings();
      await assertFails(db.collection("titles").doc("settings_config").set({
        ...valid,
        rssFeeds: {
          movies: {
            url: "https://feed.example.test/movies.atom",
            type: "movie",
            enabled: true,
          },
        },
      }));
    });

    it("rejects a non-string feed URL", async () => {
      const db = await setupAdminUser("admin-456", "admin@example.com");
      const valid = validAdminSettings();
      await assertFails(db.collection("titles").doc("settings_config").set({
        ...valid,
        rssFeeds: { movies: { url: 123, type: "movie" } },
      }));
    });

    it("rejects a non-HTTPS feed URL", async () => {
      const db = await setupAdminUser("admin-456", "admin@example.com");
      const valid = validAdminSettings();
      await assertFails(db.collection("titles").doc("settings_config").set({
        ...valid,
        rssFeeds: { movies: { url: "http://feed.example.test/movies.atom", type: "movie" } },
      }));
    });

    it("rejects a blank or overlong feed name", async () => {
      const db = await setupAdminUser("admin-456", "admin@example.com");
      const valid = validAdminSettings();
      await assertFails(db.collection("titles").doc("settings_config").set({
        ...valid,
        rssFeeds: { " ": { url: "https://feed.example.test/movies.atom", type: "movie" } },
      }));
      await assertFails(db.collection("titles").doc("settings_config").set({
        ...valid,
        rssFeeds: {
          ["n".repeat(501)]: { url: "https://feed.example.test/movies.atom", type: "movie" },
        },
      }));
    });

    it("rejects an overlong feed URL", async () => {
      const db = await setupAdminUser("admin-456", "admin@example.com");
      const valid = validAdminSettings();
      await assertFails(db.collection("titles").doc("settings_config").set({
        ...valid,
        rssFeeds: { movies: { url: `https://${"a".repeat(2041)}`, type: "movie" } },
      }));
    });

    it("rejects an unsupported feed type", async () => {
      const db = await setupAdminUser("admin-456", "admin@example.com");
      const valid = validAdminSettings();
      await assertFails(db.collection("titles").doc("settings_config").set({
        ...valid,
        rssFeeds: { movies: { url: "https://feed.example.test/movies.atom", type: "documentary" } },
      }));
    });

    it("rejects a non-string exclusion item", async () => {
      const db = await setupAdminUser("admin-456", "admin@example.com");
      const valid = validAdminSettings();
      await assertFails(db.collection("titles").doc("settings_config").set({
        ...valid,
        excludedGenres: [123],
      }));
    });

    it("rejects an empty exclusion item", async () => {
      const db = await setupAdminUser("admin-456", "admin@example.com");
      const valid = validAdminSettings();
      await assertFails(db.collection("titles").doc("settings_config").set({
        ...valid,
        excludedCountries: [""],
      }));
    });

    it("rejects an overlong exclusion item", async () => {
      const db = await setupAdminUser("admin-456", "admin@example.com");
      const valid = validAdminSettings();
      await assertFails(db.collection("titles").doc("settings_config").set({
        ...valid,
        excludedGenres: ["g".repeat(501)],
      }));
    });

    it("denies boundary-valid settings from the browser", async () => {
      const db = await setupAdminUser("admin-456", "admin@example.com");
      const valid = validAdminSettings();
      await assertFails(db.collection("titles").doc("settings_config").set({
        ...valid,
        rssFeeds: {
          ["n".repeat(500)]: { url: `https://${"a".repeat(2040)}`, type: "series" },
        },
        excludedGenres: ["g".repeat(500)],
        excludedCountries: ["c".repeat(500)],
      }));
    });

    it("rejects malformed and extra settings fields", async () => {
      const db = await setupAdminUser("admin-456", "admin@example.com");
      const valid = {
        rssFeeds: {},
        excludedGenres: [],
        excludedCountries: [],
        minMovieRating: 0,
        minSeriesRating: 0,
        minImdbVotes: 0,
        updatedBy: "admin-456",
      };
      await assertFails(db.collection("titles").doc("settings_config").set({ ...valid, extra: true }));
      await assertFails(db.collection("titles").doc("settings_config").set({ ...valid, minMovieRating: 11 }));
      await assertFails(db.collection("titles").doc("settings_config").set({ ...valid, updatedBy: "other-user" }));
    });
    
    it("denies write to omdbCache", async () => {
      const db = await setupAllowlistedUser("user-456", "admin@example.com");
      await assertFails(db.collection("omdbCache").doc("key1").set({ status: "found" }));
    });
    
    it("denies write to scanRuns", async () => {
      const db = await setupAllowlistedUser("user-456", "admin@example.com");
      await assertFails(db.collection("scanRuns").doc("run1").set({ status: "running" }));
    });

    it("allows readers to read but not write manual mappings", async () => {
      const db = await setupAllowlistedUser("user-456", "admin@example.com");
      await assertFails(db.collection("manualMappings").doc("mapping-1").set({
        rawTitle: "The Matrix",
        imdbId: "tt0133093",
        createdAt: new Date(),
        createdBy: "user-456",
      }));
    });

    it("allows admins to create and delete valid manual mappings", async () => {
      const db = await setupAdminUser("admin-456", "admin@example.com");
      const mapping = db.collection("manualMappings").doc("mapping-1");
      await assertSucceeds(mapping.set({
        rawTitle: "The Matrix",
        imdbId: "tt0133093",
        createdAt: new Date(),
        parsedTitle: "The Matrix",
        parsedYear: 1999,
        createdBy: "admin-456",
      }));
      await assertSucceeds(mapping.delete());
    });

    it("rejects malformed, extra-field, and foreign-owner mappings", async () => {
      const db = await setupAdminUser("admin-456", "admin@example.com");
      const base = {
        rawTitle: "The Matrix",
        imdbId: "tt0133093",
        createdAt: new Date(),
        createdBy: "admin-456",
      };
      await assertFails(db.collection("manualMappings").doc("bad-id").set({ ...base, imdbId: "not-an-imdb-id" }));
      await assertFails(db.collection("manualMappings").doc("extra-field").set({ ...base, extra: true }));
      await assertFails(db.collection("manualMappings").doc("foreign-owner").set({ ...base, createdBy: "other-user" }));
    });
  });

  describe("Owner-scoped users/{uid}/userTitles namespace", () => {
    it("allows allowlisted owner to write and read valid userTitles doc", async () => {
      const db = await setupAllowlistedUser("user-456", "admin@example.com");
      await assertSucceeds(
        db.collection("users").doc("user-456").collection("userTitles").doc("tt123").set({
          status: "favorite",
          userId: "user-456",
          updatedAt: new Date(),
        })
      );
      await assertSucceeds(
        db.collection("users").doc("user-456").collection("userTitles").doc("tt123").get()
      );
      await assertSucceeds(
        db.collection("users").doc("user-456").collection("userTitles").doc("tt123").delete()
      );
    });

    it("denies access to userTitles for other users or unallowed fields", async () => {
      const db = await setupAllowlistedUser("user-456", "admin@example.com");
      // Other user's path
      await assertFails(
        db.collection("users").doc("user-other").collection("userTitles").doc("tt123").get()
      );
      await assertFails(
        db.collection("users").doc("user-other").collection("userTitles").doc("tt123").set({
          status: "favorite",
          userId: "user-other",
          updatedAt: new Date(),
        })
      );
      // Invalid status
      await assertFails(
        db.collection("users").doc("user-456").collection("userTitles").doc("tt123").set({
          status: "invalid_status",
          userId: "user-456",
          updatedAt: new Date(),
        })
      );
      // Unallowed extra fields
      await assertFails(
        db.collection("users").doc("user-456").collection("userTitles").doc("tt123").set({
          status: "favorite",
          userId: "user-456",
          updatedAt: new Date(),
          extraField: "hacked",
        })
      );
    });
  });
});
