/**
 * DependencyGraph3DPage.tsx
 * 
 * 3D Force-directed graph visualization (like Misha's brain!)
 * 
 * Features:
 * - 3D rotating graph
 * - Search files
 * - Focus mode (show only dependencies of selected file)
 * - Labels on nodes
 * - Color legend
 */

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import { useParams, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import SpriteText from 'three-spritetext';

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
  source: string | GraphNode;
  target: string | GraphNode;
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

const LEGEND_ITEMS = [
  { type: 'component', label: 'Component', color: '#3b82f6' },
  { type: 'service', label: 'Service', color: '#22c55e' },
  { type: 'router', label: 'Router', color: '#f59e0b' },
  { type: 'model', label: 'Model', color: '#a855f7' },
  { type: 'utility', label: 'Utility', color: '#6366f1' },
  { type: 'file', label: 'Other', color: '#6b7280' },
];

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

  // Data state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  const [allData, setAllData] = useState<GraphData>({ nodes: [], links: [] }); // Original data
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [projectName, setProjectName] = useState('');
  const [stats, setStats] = useState({ total_files: 0, total_dependencies: 0, total_lines: 0 });

  // UI state
  const [searchQuery, setSearchQuery] = useState('');
  const [showLabels, setShowLabels] = useState(true);
  const [focusMode, setFocusMode] = useState(false);
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);

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

        const graphData = {
          nodes: data.nodes,
          links: data.edges.map((e: any) => ({
            source: e.source,
            target: e.target,
            type: e.type,
          })),
        };

        setGraphData(graphData);
        setAllData(graphData); // Save original
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
  // SEARCH & FILTER
  // ============================================================

  const searchResults = useMemo(() => {
    if (!searchQuery.trim()) return [];
    const query = searchQuery.toLowerCase();
    return allData.nodes
      .filter(node => 
        node.label.toLowerCase().includes(query) ||
        node.file_path.toLowerCase().includes(query)
      )
      .slice(0, 10);
  }, [searchQuery, allData.nodes]);

  const handleSearchSelect = (node: GraphNode) => {
    setSearchQuery('');
    setSelectedNode(node);
    
    // Focus on selected node
    if (graphRef.current) {
      const distance = 200;
      const distRatio = 1 + distance / Math.hypot(node.x || 0, node.y || 0, node.z || 0);
      graphRef.current.cameraPosition(
        { x: (node.x || 0) * distRatio, y: (node.y || 0) * distRatio, z: (node.z || 0) * distRatio },
        node,
        1000
      );
    }
  };

  // ============================================================
  // FOCUS MODE - Show only dependencies of selected file
  // ============================================================

  const handleFocusNode = useCallback((nodeId: string) => {
    if (focusedNodeId === nodeId) {
      // Unfocus - show all
      setFocusedNodeId(null);
      setFocusMode(false);
      setGraphData(allData);
      return;
    }

    setFocusedNodeId(nodeId);
    setFocusMode(true);

    // Find all connected nodes
    const connectedNodeIds = new Set<string>();
    connectedNodeIds.add(nodeId);

    allData.links.forEach(link => {
      const sourceId = typeof link.source === 'string' ? link.source : link.source.id;
      const targetId = typeof link.target === 'string' ? link.target : link.target.id;
      
      if (sourceId === nodeId) {
        connectedNodeIds.add(targetId);
      }
      if (targetId === nodeId) {
        connectedNodeIds.add(sourceId);
      }
    });

    // Filter nodes and links
    const filteredNodes = allData.nodes.filter(n => connectedNodeIds.has(n.id));
    const filteredLinks = allData.links.filter(link => {
      const sourceId = typeof link.source === 'string' ? link.source : link.source.id;
      const targetId = typeof link.target === 'string' ? link.target : link.target.id;
      return connectedNodeIds.has(sourceId) && connectedNodeIds.has(targetId);
    });

    setGraphData({
      nodes: filteredNodes,
      links: filteredLinks,
    });
  }, [focusedNodeId, allData]);

  const handleResetFocus = () => {
    setFocusedNodeId(null);
    setFocusMode(false);
    setGraphData(allData);
    setSelectedNode(null);
  };

  // ============================================================
  // NODE COLOR
  // ============================================================

  const getNodeColor = useCallback((node: GraphNode) => {
    // Highlight focused node
    if (focusedNodeId === node.id) {
      return '#ef4444'; // Red for focused
    }
    return NODE_COLORS[node.type] || LANGUAGE_COLORS[node.language] || '#6b7280';
  }, [focusedNodeId]);

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

  // ============================================================
  // 3D TEXT LABELS
  // ============================================================

  const nodeThreeObject = useCallback((node: any) => {
    if (!showLabels) return undefined;
    
    const sprite = new SpriteText(node.label);
    sprite.color = '#ffffff';
    sprite.textHeight = 4;
    sprite.backgroundColor = 'rgba(0,0,0,0.6)';
    sprite.padding = 2;
    sprite.borderRadius = 3;
    return sprite;
  }, [showLabels]);

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
  // GET DEPENDENCIES COUNT FOR SELECTED NODE
  // ============================================================

  const selectedNodeDeps = useMemo(() => {
    if (!selectedNode) return { imports: 0, importedBy: 0 };
    
    let imports = 0;
    let importedBy = 0;
    
    allData.links.forEach(link => {
      const sourceId = typeof link.source === 'string' ? link.source : link.source.id;
      const targetId = typeof link.target === 'string' ? link.target : link.target.id;
      
      if (sourceId === selectedNode.id) imports++;
      if (targetId === selectedNode.id) importedBy++;
    });
    
    return { imports, importedBy };
  }, [selectedNode, allData.links]);

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
        <div className="absolute top-0 left-0 right-0 px-5 py-3 bg-slate-900/95 z-10 flex items-center gap-4 border-b border-slate-700">
          <button
            onClick={() => navigate(-1)}
            className="px-3 py-1.5 bg-slate-800 border border-slate-600 rounded-md text-white hover:bg-slate-700 transition"
          >
            ← Back
          </button>
          
          <h1 className="text-lg font-semibold text-white m-0">
            🧠 {projectName}
          </h1>

          {/* Search */}
          <div className="relative ml-4">
            <input
              type="text"
              placeholder="🔍 Search file..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-64 px-3 py-1.5 bg-slate-800 border border-slate-600 rounded-md text-white text-sm placeholder-slate-500 focus:outline-none focus:border-primary"
            />
            
            {/* Search Results Dropdown */}
            {searchResults.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-slate-800 border border-slate-600 rounded-md shadow-xl max-h-64 overflow-auto z-50">
                {searchResults.map(node => (
                  <button
                    key={node.id}
                    onClick={() => handleSearchSelect(node)}
                    className="w-full px-3 py-2 text-left text-sm text-white hover:bg-slate-700 flex items-center gap-2"
                  >
                    <span 
                      className="w-3 h-3 rounded-full flex-shrink-0"
                      style={{ backgroundColor: getNodeColor(node) }}
                    />
                    <span className="truncate">{node.label}</span>
                    <span className="text-slate-500 text-xs ml-auto">{node.language}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Controls */}
          <div className="flex items-center gap-3 ml-4">
            <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={showLabels}
                onChange={(e) => setShowLabels(e.target.checked)}
                className="w-4 h-4 rounded border-slate-600 bg-slate-800 text-primary focus:ring-primary"
              />
              Labels
            </label>
          </div>

          {/* Focus Mode Badge */}
          {focusMode && (
            <button
              onClick={handleResetFocus}
              className="px-3 py-1 bg-red-500/20 border border-red-500/50 rounded-full text-red-400 text-xs hover:bg-red-500/30 transition flex items-center gap-1"
            >
              <span>🎯 Focus Mode</span>
              <span className="font-bold">×</span>
            </button>
          )}
          
          <div className="ml-auto flex gap-4 text-sm text-slate-400">
            <span>📁 {graphData.nodes.length}{focusMode ? `/${allData.nodes.length}` : ''}</span>
            <span>🔗 {graphData.links.length}</span>
            <span>📝 {stats.total_lines.toLocaleString()}</span>
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
          nodeThreeObject={showLabels ? nodeThreeObject : undefined}
          nodeThreeObjectExtend={showLabels}
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

        {/* Legend */}
        <div className="absolute bottom-5 left-5 bg-slate-800/90 border border-slate-700 rounded-lg p-3 text-white">
          <div className="text-xs text-slate-400 mb-2 font-medium">Legend</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            {LEGEND_ITEMS.map(item => (
              <div key={item.type} className="flex items-center gap-2 text-xs">
                <span 
                  className="w-3 h-3 rounded-full"
                  style={{ backgroundColor: item.color }}
                />
                <span className="text-slate-300">{item.label}</span>
              </div>
            ))}
          </div>
          <div className="mt-2 pt-2 border-t border-slate-700 text-xs text-slate-500">
            🖱️ Drag to rotate • Scroll to zoom
          </div>
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
            <div className="p-3 bg-slate-900 rounded-lg mb-4">
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

            {/* Dependencies Info */}
            <div className="p-3 bg-slate-900 rounded-lg mb-4">
              <div className="text-slate-400 text-xs mb-2 font-medium">Dependencies</div>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <div className="text-slate-500 text-xs mb-0.5">Imports</div>
                  <div className="font-medium text-blue-400">{selectedNodeDeps.imports} files</div>
                </div>
                <div>
                  <div className="text-slate-500 text-xs mb-0.5">Imported by</div>
                  <div className="font-medium text-green-400">{selectedNodeDeps.importedBy} files</div>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="space-y-2">
              <button
                onClick={() => handleFocusNode(selectedNode.id)}
                className={`w-full py-2.5 rounded-lg transition text-sm flex items-center justify-center gap-2 ${
                  focusedNodeId === selectedNode.id
                    ? 'bg-red-500/20 text-red-400 border border-red-500/50'
                    : 'bg-primary text-white hover:bg-primary/80'
                }`}
              >
                {focusedNodeId === selectedNode.id ? (
                  <>🔄 Show All</>
                ) : (
                  <>🎯 Focus Dependencies</>
                )}
              </button>
              
              <button
                onClick={() => navigator.clipboard.writeText(selectedNode.file_path)}
                className="w-full py-2.5 bg-slate-700 text-white rounded-lg hover:bg-slate-600 transition text-sm"
              >
                📋 Copy Path
              </button>
            </div>
          </div>
        ) : (
          <div className="p-10 text-center text-slate-500">
            <div className="text-5xl mb-3">👆</div>
            <div>Click a node to see details</div>
            <div className="text-xs mt-2">or search for a file above</div>
          </div>
        )}
      </div>
    </div>
  );
};

export default DependencyGraph3DPage;