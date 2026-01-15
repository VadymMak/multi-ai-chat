/**
 * useDependencyGraph.ts
 * 
 * Custom hook for fetching and managing dependency graph data.
 * Handles loading, error states, and caching.
 */

import { useState, useEffect, useCallback } from 'react';

// ============================================================
// TYPES
// ============================================================

export interface GraphNode {
  id: string;
  file_path: string;
  label: string;
  language: string;
  line_count: number;
  file_size: number;
  type: string;
  metadata: Record<string, any>;
}

export interface GraphEdge {
  source: string;
  target: string;
  source_path: string;
  target_path: string;
  type: string;
}

export interface GraphStats {
  total_files: number;
  total_dependencies: number;
  languages: string[];
  total_lines: number;
}

export interface DependencyGraphData {
  project_id: number;
  project_name: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  tree: string;
  stats: GraphStats;
}

export interface FileDependencies {
  imports: GraphNode[];
  importedBy: GraphNode[];
}

// ============================================================
// API FUNCTIONS
// ============================================================

const API_BASE = import.meta.env.VITE_API_URL || '';

async function fetchWithAuth(url: string): Promise<Response> {
  const token = localStorage.getItem('token');
  
  const response = await fetch(url, {
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  });
  
  if (!response.ok) {
    throw new Error(`API Error: ${response.status} ${response.statusText}`);
  }
  
  return response;
}

// ============================================================
// MAIN HOOK
// ============================================================

export function useDependencyGraph(projectId: number | string | undefined) {
  const [data, setData] = useState<DependencyGraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // Fetch graph data
  const fetchGraph = useCallback(async () => {
    if (!projectId) {
      setLoading(false);
      return;
    }
    
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetchWithAuth(
        `${API_BASE}/api/file-indexer/dependency-graph/${projectId}`
      );
      const graphData = await response.json();
      setData(graphData);
    } catch (err) {
      console.error('Failed to fetch dependency graph:', err);
      setError(err instanceof Error ? err.message : 'Failed to load graph');
    } finally {
      setLoading(false);
    }
  }, [projectId]);
  
  // Initial fetch
  useEffect(() => {
    fetchGraph();
  }, [fetchGraph]);
  
  // Refresh function
  const refresh = useCallback(() => {
    fetchGraph();
  }, [fetchGraph]);
  
  // Get dependencies for a specific file
  const getFileDependencies = useCallback((nodeId: string): FileDependencies => {
    if (!data) return { imports: [], importedBy: [] };
    
    const imports = data.edges
      .filter(e => e.source === nodeId)
      .map(e => data.nodes.find(n => n.id === e.target))
      .filter((n): n is GraphNode => n !== undefined);
    
    const importedBy = data.edges
      .filter(e => e.target === nodeId)
      .map(e => data.nodes.find(n => n.id === e.source))
      .filter((n): n is GraphNode => n !== undefined);
    
    return { imports, importedBy };
  }, [data]);
  
  // Find node by file path
  const findNodeByPath = useCallback((filePath: string): GraphNode | undefined => {
    return data?.nodes.find(n => n.file_path === filePath);
  }, [data]);
  
  // Get nodes filtered by criteria
  const getFilteredNodes = useCallback((
    searchQuery?: string,
    language?: string
  ): GraphNode[] => {
    if (!data) return [];
    
    let filtered = data.nodes;
    
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(n => 
        n.label.toLowerCase().includes(query) ||
        n.file_path.toLowerCase().includes(query)
      );
    }
    
    if (language && language !== 'all') {
      filtered = filtered.filter(n => n.language === language);
    }
    
    return filtered;
  }, [data]);
  
  // Get edges for filtered nodes
  const getFilteredEdges = useCallback((nodeIds: Set<string>): GraphEdge[] => {
    if (!data) return [];
    
    return data.edges.filter(e => 
      nodeIds.has(e.source) && nodeIds.has(e.target)
    );
  }, [data]);
  
  return {
    data,
    loading,
    error,
    refresh,
    getFileDependencies,
    findNodeByPath,
    getFilteredNodes,
    getFilteredEdges,
  };
}

// ============================================================
// ADDITIONAL HOOKS
// ============================================================

/**
 * Hook for fetching single file dependencies
 */
export function useFileDependencies(
  projectId: number | string | undefined,
  filePath: string | undefined
) {
  const [dependencies, setDependencies] = useState<string[]>([]);
  const [dependents, setDependents] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  useEffect(() => {
    if (!projectId || !filePath) return;
    
    const fetchDeps = async () => {
      setLoading(true);
      setError(null);
      
      try {
        // Fetch dependencies (what this file imports)
        const depsResponse = await fetchWithAuth(
          `${API_BASE}/api/file-indexer/dependencies/${projectId}/${encodeURIComponent(filePath)}`
        );
        const depsData = await depsResponse.json();
        setDependencies(depsData.dependencies || []);
        
        // Fetch dependents (what imports this file)
        const dependentsResponse = await fetchWithAuth(
          `${API_BASE}/api/file-indexer/dependents/${projectId}/${encodeURIComponent(filePath)}`
        );
        const dependentsData = await dependentsResponse.json();
        setDependents(dependentsData.dependents || []);
        
      } catch (err) {
        console.error('Failed to fetch file dependencies:', err);
        setError(err instanceof Error ? err.message : 'Failed to load');
      } finally {
        setLoading(false);
      }
    };
    
    fetchDeps();
  }, [projectId, filePath]);
  
  return { dependencies, dependents, loading, error };
}

/**
 * Hook for project stats
 */
export function useProjectStats(projectId: number | string | undefined) {
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [loading, setLoading] = useState(false);
  
  useEffect(() => {
    if (!projectId) return;
    
    const fetchStats = async () => {
      setLoading(true);
      try {
        const response = await fetchWithAuth(
          `${API_BASE}/api/file-indexer/stats/${projectId}`
        );
        const data = await response.json();
        setStats(data);
      } catch (err) {
        console.error('Failed to fetch stats:', err);
      } finally {
        setLoading(false);
      }
    };
    
    fetchStats();
  }, [projectId]);
  
  return { stats, loading };
}

export default useDependencyGraph;