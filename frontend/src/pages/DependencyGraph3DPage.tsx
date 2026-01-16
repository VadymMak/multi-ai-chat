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
 * - Sidebar with file details
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
// CONSTANTS
// ============================================================

const SIDEBAR_WIDTH = 320;
const TOOLBAR_HEIGHT = 56;

// ============================================================
// MAIN COMPONENT
// ============================================================

const DependencyGraph3DPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const { isAuthenticated, token } = useAuthStore();
  const graphRef = useRef<any>();
  const containerRef = useRef<HTMLDivElement>(null);

  // Data state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  const [allData, setAllData] = useState<GraphData>({ nodes: [], links: [] });
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [projectName, setProjectName] = useState('');
  const [stats, setStats] = useState({ total_files: 0, total_dependencies: 0, total_lines: 0 });

  // UI state
  const [searchQuery, setSearchQuery] = useState('');
  const [showLabels, setShowLabels] = useState(true);
  const [focusMode, setFocusMode] = useState(false);
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  // ============================================================
  // HANDLE RESIZE
  // ============================================================

  useEffect(() => {
    const updateDimensions = () => {
      setDimensions({
        width: window.innerWidth - SIDEBAR_WIDTH,
        height: window.innerHeight,
      });
    };

    updateDimensions();
    window.addEventListener('resize', updateDimensions);
    return () => window.removeEventListener('resize', updateDimensions);
  }, []);

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
        setAllData(graphData);
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
  // FOCUS MODE
  // ============================================================

  const handleFocusNode = useCallback((nodeId: string) => {
    if (focusedNodeId === nodeId) {
      setFocusedNodeId(null);
      setFocusMode(false);
      setGraphData(allData);
      return;
    }

    setFocusedNodeId(nodeId);
    setFocusMode(true);

    const connectedNodeIds = new Set<string>();
    connectedNodeIds.add(nodeId);

    allData.links.forEach(link => {
      const sourceId = typeof link.source === 'string' ? link.source : link.source.id;
      const targetId = typeof link.target === 'string' ? link.target : link.target.id;
      
      if (sourceId === nodeId) connectedNodeIds.add(targetId);
      if (targetId === nodeId) connectedNodeIds.add(sourceId);
    });

    const filteredNodes = allData.nodes.filter(n => connectedNodeIds.has(n.id));
    const filteredLinks = allData.links.filter(link => {
      const sourceId = typeof link.source === 'string' ? link.source : link.source.id;
      const targetId = typeof link.target === 'string' ? link.target : link.target.id;
      return connectedNodeIds.has(sourceId) && connectedNodeIds.has(targetId);
    });

    setGraphData({ nodes: filteredNodes, links: filteredLinks });
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
    if (focusedNodeId === node.id) return '#ef4444';
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
  // DEPENDENCIES COUNT
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
  // RENDER - LOADING
  // ============================================================

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-900 text-white">
        <div className="text-center">
          <div className="text-5xl mb-4">🧠</div>
          <div className="text-slate-400">Loading 3D Brain...</div>
        </div>
      </div>
    );
  }

  // ============================================================
  // RENDER - ERROR
  // ============================================================

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-900 text-white">
        <div className="text-center">
          <div className="text-5xl mb-4">❌</div>
          <div className="text-red-400 mb-4">{error}</div>
          <button
            onClick={() => navigate(-1)}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition"
          >
            Go Back
          </button>
        </div>
      </div>
    );
  }

  // ============================================================
  // RENDER - MAIN
  // ============================================================

  return (
    <div 
      style={{ 
        display: 'flex', 
        height: '100vh', 
        width: '100vw',
        backgroundColor: '#0f172a',
        overflow: 'hidden'
      }}
    >
      {/* 3D Graph Container */}
      <div 
        ref={containerRef}
        style={{ 
          flex: 1,
          position: 'relative',
          width: `calc(100vw - ${SIDEBAR_WIDTH}px)`,
          height: '100vh'
        }}
      >
        {/* Toolbar */}
        <div 
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: TOOLBAR_HEIGHT,
            padding: '0 20px',
            backgroundColor: 'rgba(15, 23, 42, 0.95)',
            borderBottom: '1px solid #334155',
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            zIndex: 100
          }}
        >
          <button
            onClick={() => navigate(-1)}
            style={{
              padding: '6px 12px',
              backgroundColor: '#1e293b',
              border: '1px solid #475569',
              borderRadius: 6,
              color: 'white',
              cursor: 'pointer'
            }}
          >
            ← Back
          </button>
          
          <h1 style={{ fontSize: 18, fontWeight: 600, color: 'white', margin: 0 }}>
            🧠 {projectName}
          </h1>

          {/* Search */}
          <div style={{ position: 'relative', marginLeft: 16 }}>
            <input
              type="text"
              placeholder="🔍 Search file..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                width: 256,
                padding: '6px 12px',
                backgroundColor: '#1e293b',
                border: '1px solid #475569',
                borderRadius: 6,
                color: 'white',
                fontSize: 14,
                outline: 'none'
              }}
            />
            
            {searchResults.length > 0 && (
              <div 
                style={{
                  position: 'absolute',
                  top: '100%',
                  left: 0,
                  right: 0,
                  marginTop: 4,
                  backgroundColor: '#1e293b',
                  border: '1px solid #475569',
                  borderRadius: 6,
                  maxHeight: 256,
                  overflowY: 'auto',
                  zIndex: 200
                }}
              >
                {searchResults.map(node => (
                  <button
                    key={node.id}
                    onClick={() => handleSearchSelect(node)}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      backgroundColor: 'transparent',
                      border: 'none',
                      color: 'white',
                      fontSize: 14,
                      textAlign: 'left',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8
                    }}
                    onMouseOver={(e) => e.currentTarget.style.backgroundColor = '#334155'}
                    onMouseOut={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                  >
                    <span 
                      style={{
                        width: 12,
                        height: 12,
                        borderRadius: '50%',
                        backgroundColor: getNodeColor(node),
                        flexShrink: 0
                      }}
                    />
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {node.label}
                    </span>
                    <span style={{ color: '#64748b', fontSize: 12 }}>{node.language}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Labels Toggle */}
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#cbd5e1', fontSize: 14, cursor: 'pointer', marginLeft: 16 }}>
            <input
              type="checkbox"
              checked={showLabels}
              onChange={(e) => setShowLabels(e.target.checked)}
              style={{ width: 16, height: 16 }}
            />
            Labels
          </label>

          {/* Focus Mode Badge */}
          {focusMode && (
            <button
              onClick={handleResetFocus}
              style={{
                padding: '4px 12px',
                backgroundColor: 'rgba(239, 68, 68, 0.2)',
                border: '1px solid rgba(239, 68, 68, 0.5)',
                borderRadius: 16,
                color: '#f87171',
                fontSize: 12,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 4
              }}
            >
              🎯 Focus Mode ×
            </button>
          )}
          
          {/* Stats */}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 16, color: '#94a3b8', fontSize: 14 }}>
            <span>📁 {graphData.nodes.length}{focusMode ? `/${allData.nodes.length}` : ''}</span>
            <span>🔗 {graphData.links.length}</span>
            <span>📝 {stats.total_lines.toLocaleString()}</span>
          </div>
        </div>

        {/* 3D Force Graph */}
        <ForceGraph3D
          ref={graphRef}
          width={dimensions.width}
          height={dimensions.height}
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
        <div 
          style={{
            position: 'absolute',
            bottom: 20,
            left: 20,
            backgroundColor: 'rgba(30, 41, 59, 0.95)',
            border: '1px solid #334155',
            borderRadius: 8,
            padding: 12,
            color: 'white',
            zIndex: 100
          }}
        >
          <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 8, fontWeight: 500 }}>Legend</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 16px' }}>
            {LEGEND_ITEMS.map(item => (
              <div key={item.type} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                <span 
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: '50%',
                    backgroundColor: item.color
                  }}
                />
                <span style={{ color: '#cbd5e1' }}>{item.label}</span>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid #334155', fontSize: 11, color: '#64748b' }}>
            🖱️ Drag to rotate • Scroll to zoom
          </div>
        </div>
      </div>

      {/* Sidebar */}
      <div 
        style={{
          width: SIDEBAR_WIDTH,
          minWidth: SIDEBAR_WIDTH,
          height: '100vh',
          backgroundColor: '#1e293b',
          borderLeft: '1px solid #334155',
          overflowY: 'auto',
          color: 'white'
        }}
      >
        {selectedNode ? (
          <div style={{ padding: 20 }}>
            {/* Header */}
            <div style={{ marginBottom: 20 }}>
              <div 
                style={{
                  width: 48,
                  height: 48,
                  borderRadius: 12,
                  backgroundColor: getNodeColor(selectedNode),
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 24,
                  marginBottom: 12
                }}
              >
                {getLanguageIcon(selectedNode.language)}
              </div>
              <h2 style={{ fontSize: 16, fontWeight: 600, wordBreak: 'break-all', marginBottom: 4 }}>
                {selectedNode.label}
              </h2>
              <div style={{ fontSize: 12, color: '#94a3b8', wordBreak: 'break-all' }}>
                {selectedNode.file_path}
              </div>
            </div>

            {/* File Info */}
            <div style={{ padding: 12, backgroundColor: '#0f172a', borderRadius: 8, marginBottom: 16 }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <div style={{ fontSize: 11, color: '#64748b', marginBottom: 2 }}>Language</div>
                  <div style={{ fontSize: 14, fontWeight: 500 }}>{selectedNode.language}</div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#64748b', marginBottom: 2 }}>Type</div>
                  <div style={{ fontSize: 14, fontWeight: 500 }}>{selectedNode.type}</div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#64748b', marginBottom: 2 }}>Lines</div>
                  <div style={{ fontSize: 14, fontWeight: 500 }}>{selectedNode.line_count}</div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#64748b', marginBottom: 2 }}>Size</div>
                  <div style={{ fontSize: 14, fontWeight: 500 }}>{(selectedNode.file_size / 1024).toFixed(1)} KB</div>
                </div>
              </div>
            </div>

            {/* Dependencies Info */}
            <div style={{ padding: 12, backgroundColor: '#0f172a', borderRadius: 8, marginBottom: 16 }}>
              <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 8, fontWeight: 500 }}>Dependencies</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <div style={{ fontSize: 11, color: '#64748b', marginBottom: 2 }}>Imports</div>
                  <div style={{ fontSize: 14, fontWeight: 500, color: '#60a5fa' }}>{selectedNodeDeps.imports} files</div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#64748b', marginBottom: 2 }}>Imported by</div>
                  <div style={{ fontSize: 14, fontWeight: 500, color: '#4ade80' }}>{selectedNodeDeps.importedBy} files</div>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <button
                onClick={() => handleFocusNode(selectedNode.id)}
                style={{
                  width: '100%',
                  padding: '10px 16px',
                  backgroundColor: focusedNodeId === selectedNode.id ? 'rgba(239, 68, 68, 0.2)' : '#3b82f6',
                  border: focusedNodeId === selectedNode.id ? '1px solid rgba(239, 68, 68, 0.5)' : 'none',
                  borderRadius: 8,
                  color: focusedNodeId === selectedNode.id ? '#f87171' : 'white',
                  fontSize: 14,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 8
                }}
              >
                {focusedNodeId === selectedNode.id ? '🔄 Show All' : '🎯 Focus Dependencies'}
              </button>
              
              <button
                onClick={() => navigator.clipboard.writeText(selectedNode.file_path)}
                style={{
                  width: '100%',
                  padding: '10px 16px',
                  backgroundColor: '#334155',
                  border: 'none',
                  borderRadius: 8,
                  color: 'white',
                  fontSize: 14,
                  cursor: 'pointer'
                }}
              >
                📋 Copy Path
              </button>
            </div>
          </div>
        ) : (
          <div style={{ padding: 40, textAlign: 'center', color: '#64748b' }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>👆</div>
            <div>Click a node to see details</div>
            <div style={{ fontSize: 12, marginTop: 8 }}>or search for a file above</div>
          </div>
        )}
      </div>
    </div>
  );
};

export default DependencyGraph3DPage;