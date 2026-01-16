/**
 * DependencyGraph3DPage.tsx
 * 
 * 3D Force-directed graph visualization (like Misha's brain!)
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';

// ============================================================
// TYPES
// ============================================================

interface GraphNode {
  id: string;
  file_path: string;
  label: string;
  language: string;
  line_count: number;
  file_size: number;
  type: string;
  x?: number;
  y?: number;
  z?: number;
}

interface GraphEdge {
  source: string;
  target: string;
  type: string;
}

interface GraphData {
  nodes: GraphNode[];
  links: GraphEdge[];
}

// ============================================================
// COLORS BY TYPE
// ============================================================

const NODE_COLORS: Record<string, string> = {
  component: '#3b82f6',
  service: '#22c55e',
  router: '#f59e0b',
  model: '#a855f7',
  utility: '#6366f1',
  file: '#6b7280',
};

const LANGUAGE_COLORS: Record<string, string> = {
  typescript: '#3178c6',
  javascript: '#f7df1e',
  python: '#3776ab',
  css: '#264de4',
  html: '#e34c26',
  json: '#292929',
  markdown: '#083fa1',
};

// ============================================================
// MAIN COMPONENT
// ============================================================

const DependencyGraph3DPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { isAuthenticated, token } = useAuthStore();
  const graphRef = useRef<any>();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [projectName, setProjectName] = useState('');
  const [stats, setStats] = useState({ total_files: 0, total_dependencies: 0, total_lines: 0 });

  // ============================================================
  // FETCH DATA
  // ============================================================

  useEffect(() => {
    const fetchGraph = async () => {
      if (!projectId || !isAuthenticated || !token) return;

      setLoading(true);
      setError(null);

      try {
        const response = await fetch(
          `${import.meta.env.VITE_API_BASE_URL || ''}/file-indexer/dependency-graph/${projectId}`,
          {
            headers: {
              'Authorization': `Bearer ${token}`,
              'Content-Type': 'application/json',
            },
          }
        );

        if (!response.ok) throw new Error(`Failed to fetch: ${response.status}`);

        const data = await response.json();
        console.log('📊 Graph data:', data.nodes.length, 'nodes,', data.edges.length, 'edges');

        setGraphData({
          nodes: data.nodes,
          links: data.edges.map((e: any) => ({
            source: e.source,
            target: e.target,
            type: e.type,
          })),
        });

        setProjectName(data.project_name);
        setStats(data.stats);
      } catch (err) {
        console.error('Failed to fetch:', err);
        setError(err instanceof Error ? err.message : 'Failed to load');
      } finally {
        setLoading(false);
      }
    };

    fetchGraph();
  }, [projectId, isAuthenticated, token]);

  // ============================================================
  // NODE COLOR
  // ============================================================

  const getNodeColor = useCallback((node: GraphNode) => {
    return NODE_COLORS[node.type] || LANGUAGE_COLORS[node.language] || '#6b7280';
  }, []);

  // ============================================================
  // NODE CLICK
  // ============================================================

  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelectedNode(node);
    
    if (graphRef.current) {
      const distance = 200;
      const distRatio = 1 + distance / Math.hypot(node.x || 0, node.y || 0, node.z || 0);
      graphRef.current.cameraPosition(
        { x: (node.x || 0) * distRatio, y: (node.y || 0) * distRatio, z: (node.z || 0) * distRatio },
        node,
        2000
      );
    }
  }, []);

  const getLanguageIcon = (language: string) => {
    const icons: Record<string, string> = {
      typescript: '🔷',
      javascript: '🟨',
      python: '🐍',
      css: '🎨',
      html: '📄',
      json: '📋',
      markdown: '📝',
    };
    return icons[language] || '📄';
  };

  // ============================================================
  // RENDER
  // ============================================================

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-900 text-white">
        <div className="text-center">
          <div className="text-5xl mb-4">🧠</div>
          <div className="text-text-secondary">Loading 3D Brain...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-900 text-white">
        <div className="text-center">
          <div className="text-5xl mb-4">❌</div>
          <div className="text-error mb-4">{error}</div>
          <button
            onClick={() => navigate(-1)}
            className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/80 transition"
          >
            Go Back
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-slate-900">
      {/* 3D Graph */}
      <div className="flex-1 relative">
        {/* Toolbar */}
        <div className="absolute top-0 left-0 right-0 px-5 py-3 bg-slate-900/90 z-10 flex items-center gap-4 border-b border-slate-700">
          <button
            onClick={() => navigate(-1)}
            className="px-3 py-1.5 bg-slate-800 border border-slate-600 rounded-md text-white hover:bg-slate-700 transition"
          >
            ← Back
          </button>
          
          <h1 className="text-lg font-semibold text-white m-0">
            🧠 {projectName} - 3D Brain
          </h1>
          
          <div className="ml-auto flex gap-4 text-sm text-slate-400">
            <span>📁 {stats.total_files} files</span>
            <span>🔗 {stats.total_dependencies} deps</span>
            <span>📝 {stats.total_lines.toLocaleString()} lines</span>
          </div>
        </div>

        {/* 3D Force Graph */}
        <ForceGraph3D
          ref={graphRef}
          graphData={graphData}
          nodeLabel={(node: any) => `${node.label}\n${node.language} • ${node.line_count} lines`}
          nodeColor={(node: any) => getNodeColor(node)}
          nodeVal={(node: any) => Math.max(3, Math.sqrt(node.line_count || 10))}
          nodeOpacity={0.9}
          linkColor={() => '#475569'}
          linkOpacity={0.6}
          linkWidth={1}
          linkDirectionalParticles={2}
          linkDirectionalParticleSpeed={0.005}
          linkDirectionalParticleWidth={2}
          onNodeClick={handleNodeClick}
          backgroundColor="#0f172a"
          showNavInfo={false}
        />

        {/* Help hint */}
        <div className="absolute bottom-5 left-5 text-slate-500 text-xs">
          🖱️ Drag to rotate • Scroll to zoom • Click node for details
        </div>
      </div>

      {/* Sidebar - Node Details */}
      <div className="w-80 bg-slate-800 border-l border-slate-700 overflow-auto text-white">
        {selectedNode ? (
          <div className="p-5">
            {/* Header */}
            <div className="mb-5">
              <div 
                className="w-12 h-12 rounded-xl flex items-center justify-center text-2xl mb-3"
                style={{ backgroundColor: getNodeColor(selectedNode) }}
              >
                {getLanguageIcon(selectedNode.language)}
              </div>
              <h2 className="text-base font-semibold break-all mb-1">
                {selectedNode.label}
              </h2>
              <div className="text-xs text-slate-400 break-all">
                {selectedNode.file_path}
              </div>
            </div>

            {/* File Info */}
            <div className="p-3 bg-slate-900 rounded-lg mb-5">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="text-slate-500 text-xs mb-0.5">Language</div>
                  <div className="font-medium">{selectedNode.language}</div>
                </div>
                <div>
                  <div className="text-slate-500 text-xs mb-0.5">Type</div>
                  <div className="font-medium">{selectedNode.type}</div>
                </div>
                <div>
                  <div className="text-slate-500 text-xs mb-0.5">Lines</div>
                  <div className="font-medium">{selectedNode.line_count}</div>
                </div>
                <div>
                  <div className="text-slate-500 text-xs mb-0.5">Size</div>
                  <div className="font-medium">
                    {(selectedNode.file_size / 1024).toFixed(1)} KB
                  </div>
                </div>
              </div>
            </div>

            {/* Actions */}
            <button
              onClick={() => navigator.clipboard.writeText(selectedNode.file_path)}
              className="w-full py-2.5 bg-primary text-white rounded-lg hover:bg-primary/80 transition text-sm"
            >
              📋 Copy Path
            </button>
          </div>
        ) : (
          <div className="p-10 text-center text-slate-500">
            <div className="text-5xl mb-3">👆</div>
            <div>Click a node to see details</div>
          </div>
        )}
      </div>
    </div>
  );
};

export default DependencyGraph3DPage;