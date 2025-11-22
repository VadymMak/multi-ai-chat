// File: frontend/src/services/SessionManager.ts
/**
 * SessionManager - Centralized session lifecycle management
 *
 * Responsibilities:
 * - Coordinate login/logout/restore across all stores
 * - Prevent race conditions with initialization flag
 * - Provide clear logging for debugging
 * - Orchestrate store interactions without business logic
 */

import { useAuthStore } from "../store/authStore";
import { useChatStore } from "../store/chatStore";
import { useProjectStore } from "../store/projectStore";
import { useMemoryStore } from "../store/memoryStore";
import { getKnownRoles } from "../constants/roles";

/**
 * SessionManager - Singleton instance
 */
class SessionManager {
  private static instance: SessionManager | null = null;
  private isInitializing = false;
  private initializationPromise: Promise<void> | null = null;

  private constructor() {
    console.log("🔧 [SessionManager] Instance created");
  }

  /**
   * Get singleton instance
   */
  public static getInstance(): SessionManager {
    if (!SessionManager.instance) {
      SessionManager.instance = new SessionManager();
    }
    return SessionManager.instance;
  }

  /**
   * Handle user login
   * Coordinates auth and initial session setup
   */
  public async handleLogin(username: string, password: string): Promise<void> {
    console.log("🔐 [SessionManager] handleLogin started for:", username);

    try {
      // Step 1: Authenticate user
      console.log("  ↳ Step 1: Authenticating...");
      const authStore = useAuthStore.getState();
      await authStore.login(username, password);
      console.log("  ✓ Step 1: Authentication successful");

      // Step 2: Wait for auth state to update
      console.log("  ↳ Step 2: Verifying auth state...");
      const { isAuthenticated, user } = useAuthStore.getState();
      if (!isAuthenticated || !user) {
        throw new Error("Authentication state not properly set");
      }
      console.log("  ✓ Step 2: Auth state verified, user:", user.username);

      // Step 3: Initialize session data
      console.log("  ↳ Step 3: Initializing session...");
      await this.initializeSession();
      console.log("  ✓ Step 3: Session initialized");

      console.log("✅ [SessionManager] handleLogin completed successfully");
    } catch (error) {
      console.error("❌ [SessionManager] handleLogin failed:", error);
      throw error;
    }
  }

  /**
   * Handle user logout
   * Clears all session data and redirects to login
   */
  public async handleLogout(): Promise<void> {
    console.log("👋 [SessionManager] handleLogout started");

    try {
      // Step 1: Clear chat store
      console.log("  ↳ Step 1: Clearing chat store...");
      const chatStore = useChatStore.getState();
      chatStore.clearMessages();
      chatStore.setChatSessionId(null);
      chatStore.setLastSessionMarker(null);
      chatStore.setSessionReady(false);
      console.log("  ✓ Step 1: Chat store cleared");

      // Step 2: Clear project store
      console.log("  ↳ Step 2: Clearing project store...");
      const projectStore = useProjectStore.getState();
      projectStore.setProjectId(null);
      console.log("  ✓ Step 2: Project store cleared");

      // Step 3: Clear memory store
      console.log("  ↳ Step 3: Clearing memory store...");
      const memoryStore = useMemoryStore.getState();
      memoryStore.clearRole();
      console.log("  ✓ Step 3: Memory store cleared");

      // Step 4: Clear auth and redirect (this will clear localStorage)
      console.log("  ↳ Step 4: Clearing auth and redirecting...");
      const authStore = useAuthStore.getState();
      authStore.clearAuth();
      console.log("  ✓ Step 4: Auth cleared");

      // Step 5: Redirect to login
      console.log("  ↳ Step 5: Redirecting to login...");
      window.location.href = "/login";
      console.log("  ✓ Step 5: Redirected");

      console.log("✅ [SessionManager] handleLogout completed");
    } catch (error) {
      console.error("❌ [SessionManager] handleLogout failed:", error);
      // Still redirect even if there's an error
      window.location.href = "/login";
    }
  }

  /**
   * Restore session on page load
   * Checks auth status and restores session state
   */
  public async restoreSessionOnPageLoad(): Promise<boolean> {
    console.log("🔄 [SessionManager] restoreSessionOnPageLoad started");

    // Prevent multiple simultaneous initializations
    if (this.isInitializing && this.initializationPromise) {
      console.log("  ⏳ Already initializing, waiting...");
      await this.initializationPromise;
      return true;
    }

    if (this.isInitializing) {
      console.log("  ⚠️ Already initializing but no promise, creating new...");
    }

    this.isInitializing = true;
    this.initializationPromise = this._restoreSessionInternal();

    try {
      await this.initializationPromise;
      console.log("✅ [SessionManager] restoreSessionOnPageLoad completed");
      return true;
    } catch (error) {
      console.error(
        "❌ [SessionManager] restoreSessionOnPageLoad failed:",
        error
      );
      return false;
    } finally {
      this.isInitializing = false;
      this.initializationPromise = null;
    }
  }

  /**
   * Internal method for session restoration
   */
  private async _restoreSessionInternal(): Promise<void> {
    try {
      // Step 1: Check authentication
      console.log("  ↳ Step 1: Checking authentication...");
      const authStore = useAuthStore.getState();

      if (!authStore.token) {
        console.log("  ✗ Step 1: No token found, user not authenticated");
        return;
      }

      await authStore.checkAuth();
      const { isAuthenticated, user } = useAuthStore.getState();

      if (!isAuthenticated || !user) {
        console.log("  ✗ Step 1: Auth check failed");
        return;
      }
      console.log("  ✓ Step 1: User authenticated:", user.username);

      // Step 2: Initialize session data
      console.log("  ↳ Step 2: Initializing session...");
      await this.initializeSession();
      console.log("  ✓ Step 2: Session initialized");
    } catch (error) {
      console.error("  ✗ Error during session restoration:", error);
      throw error;
    }
  }

  /**
   * Initialize session data (role, project, chat)
   * Called after successful authentication
   */
  private async initializeSession(): Promise<void> {
    console.log("  🚀 [SessionManager] initializeSession started");

    try {
      // Step 1: Wait for store hydration
      console.log("    ↳ Step 1: Waiting for store hydration...");
      await this.waitForStoreHydration();
      console.log("    ✓ Step 1: Stores hydrated");

      // Step 2: Initialize role (from persisted state or fallback)
      console.log("    ↳ Step 2: Initializing role...");
      const memoryStore = useMemoryStore.getState();
      let currentRole = memoryStore.role;

      if (!currentRole) {
        const knownRoles = getKnownRoles();
        if (knownRoles.length > 0) {
          currentRole = knownRoles[0];
          memoryStore.setRole(currentRole);
          console.log("    ✓ Step 2: Fallback role set:", currentRole.name);
        } else {
          console.warn("    ⚠️ Step 2: No roles available");
        }
      } else {
        console.log("    ✓ Step 2: Role already set:", currentRole.name);
      }

      if (!currentRole) {
        console.warn("    ⚠️ Cannot proceed without a role");
        return;
      }

      // Step 3: Fetch and initialize projects for the role
      console.log(
        "    ↳ Step 3: Fetching projects for role:",
        currentRole.name
      );
      const projectStore = useProjectStore.getState();
      const projects = await projectStore.fetchProjectsForRole(currentRole.id);
      console.log(`    ✓ Step 3: Fetched ${projects.length} projects`);

      // Step 4: Ensure a project is selected
      console.log("    ↳ Step 4: Ensuring project selection...");
      let currentProjectId = projectStore.projectId;

      if (!currentProjectId && projects.length > 0) {
        currentProjectId = projects[0].id;
        projectStore.setProjectId(currentProjectId);
        console.log(
          "    ✓ Step 4: Auto-selected first project:",
          currentProjectId
        );
      } else if (currentProjectId) {
        console.log(
          "    ✓ Step 4: Project already selected:",
          currentProjectId
        );
      } else {
        console.warn("    ⚠️ Step 4: No projects available");

        // ✅ Set sessionReady = true даже если нет проектов
        // Это позволит показать Welcome Screen вместо блокировки
        const chatStore = useChatStore.getState();
        chatStore.setSessionReady(true);
        console.log("    ✅ Step 4: Session ready (empty state mode)");
        return;
      }

      // Step 5: Initialize/restore chat session (only if we have a project)
      if (currentProjectId) {
        console.log("    ↳ Step 5: Initializing chat session...");
        const chatStore = useChatStore.getState();

        // Use chatStore's built-in method to initialize the session
        await chatStore.initializeChatSession(currentProjectId, currentRole.id);

        console.log("    ✓ Step 5: Chat session initialized");
      }

      console.log("  ✅ [SessionManager] initializeSession completed");
    } catch (error) {
      console.error("  ❌ [SessionManager] initializeSession failed:", error);
      throw error;
    }
  }

  /**
   * Wait for store hydration to complete
   * Prevents race conditions with persisted state loading
   */
  private async waitForStoreHydration(timeoutMs = 3000): Promise<void> {
    const startTime = Date.now();

    return new Promise<void>((resolve, reject) => {
      const checkHydration = () => {
        const projectStore = useProjectStore.getState();
        const memoryStore = useMemoryStore.getState();

        const projectHydrated = projectStore.hasHydrated;
        const memoryHydrated = memoryStore.hasHydrated;

        if (projectHydrated && memoryHydrated) {
          console.log("      ✓ All stores hydrated");
          resolve();
          return;
        }

        if (Date.now() - startTime > timeoutMs) {
          console.warn("      ⚠️ Store hydration timeout, proceeding anyway");
          resolve();
          return;
        }

        // Check again in 50ms
        setTimeout(checkHydration, 50);
      };

      checkHydration();
    });
  }

  /**
   * Check if currently initializing
   */
  public isCurrentlyInitializing(): boolean {
    return this.isInitializing;
  }
}

// Export singleton instance
export const sessionManager = SessionManager.getInstance();
export default sessionManager;
