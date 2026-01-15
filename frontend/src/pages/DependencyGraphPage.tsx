/**
 * DependencyGraphPage.tsx
 * 
 * Interactive dependency graph visualization using React Flow.
 * Shows how files in the project connect to each other.
 * 
 * Features:
 * - Interactive zoom/pan
 * - Click node to see file details
 * - Color coding by file type
 * - Search/filter nodes
 * - Minimap for navigation
 * - Export as PNG
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import ReactFlow, {
  Node,
  Edge,
  Controls,
  MiniMap,
  Background,
  useNodesState,
  useEdgesState,
  MarkerType,
  Position,
  ConnectionMode,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { useAuthStore } from '../store/authStore';

import { useParams, useNavigate } from 'react-router-dom';

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
  metadata: Record<string, any>;
}

interface GraphEdge {
  source: string;
  target: string;
  source_path: string;
  target_path: string;
  type: string;
}

interface GraphStats {
  total_files: number;
  total_dependencies: number;
  languages: string[];
  total_lines: number;
}

interface DependencyGraphResponse {
  project_id: number;
  project_name: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  tree: string;
  stats: GraphStats;
}

// ============================================================
// CONSTANTS
// ============================================================

// Color scheme for different file types
const NODE_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  component: { bg: '#dbeafe', border: '#3b82f6', text: '#1e40af' },  // Blue
  service: { bg: '#dcfce7', border: '#22c55e', text: '#166534' },    // Green
  router: { bg: '#fef3c7', border: '#f59e0b', text: '#92400e' },     // Amber
  model: { bg: '#f3e8ff', border: '#a855f7', text: '#6b21a8' },      // Purple
  utility: { bg: '#e0e7ff', border: '#6366f1', text: '#3730a3' },    // Indigo
  file: { bg: '#f3f4f6', border: '#6b7280', text: '#374151' },       // Gray (default)
};

// Language icons
const LANGUAGE_ICONS: Record<string, string> = {
  typescript: '🔷',
  javascript: '🟨',
  python: '🐍',
  rust: '🦀',
  go: '🐹',
  java: '☕',
  css: '🎨',
  html: '📄',
  json: '📋',
  markdown: '📝',
};

// ============================================================
// CUSTOM NODE COMPONENT
// ============================================================

interface FileNodeProps {
  data: {
    label: string;
    language: string;
    lineCount: number;
    fileType: string;
    filePath: string;
    isSelected: boolean;
    onClick: () => void;
  };
}

const FileNode: React.FC<FileNodeProps> = ({ data }) => {
  const colors = NODE_COLORS[data.fileType] || NODE_COLORS.file;
  const icon = LANGUAGE_ICONS[data.language] || '📄';

  return (
    <div
      onClick={data.onClick}
      style={{
        padding: '10px 14px',
        borderRadius: '8px',
        backgroundColor: colors.bg,
        border: `2px solid ${data.isSelected ? '#ef4444' : colors.border}`,
        boxShadow: data.isSelected 
          ? '0 0 0 3px rgba(239, 68, 68, 0.3)' 
          : '0 2px 4px rgba(0,0,0,0.1)',
        cursor: 'pointer',
        minWidth: '120px',
        transition: 'all 0.2s ease',
      }}
    >
      <div style={{ 
        display: 'flex', 
        alignItems: 'center', 
        gap: '6px',
        marginBottom: '4px'
      }}>
        <span style={{ fontSize: '14px' }}>{icon}</span>
        <span style={{ 
          fontWeight: 600, 
          color: colors.text,
          fontSize: '13px',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          maxWidth: '150px'
        }}>
          {data.label}
        </span>
      </div>
      <div style={{ 
        fontSize: '11px', 
        color: '#6b7280',
        display: 'flex',
        gap: '8px'
      }}>
        <span>{data.language}</span>
        <span>•</span>
        <span>{data.lineCount} lines</span>
      </div>
    </div>
  );
};

// Register custom node types
const nodeTypes = {
  fileNode: FileNode,
};

// ============================================================
// LAYOUT ALGORITHM (Dagre-like hierarchical layout)
// ============================================================

function calculateLayout(
  nodes: GraphNode[], 
  edges: GraphEdge[]
): { nodes: Node[]; edges: Edge[] } {
  // Build adjacency lists
  const incomingEdges: Record<string, string[]> = {};
  const outgoingEdges: Record<string, string[]> = {};
  
  nodes.forEach(n => {
    incomingEdges[n.id] = [];
    outgoingEdges[n.id] = [];
  });
  
  edges.forEach(e => {
    if (incomingEdges[e.target]) {
      incomingEdges[e.target].push(e.source);
    }
    if (outgoingEdges[e.source]) {
      outgoingEdges[e.source].push(e.target);
    }
  });
  
  // Calculate levels (topological sort)
  const levels: Record<string, number> = {};
  const visited = new Set<string>();
  
  function calculateLevel(nodeId: string): number {
    if (levels[nodeId] !== undefined) return levels[nodeId];
    if (visited.has(nodeId)) return 0; // Cycle detected
    
    visited.add(nodeId);
    
    const incoming = incomingEdges[nodeId] || [];
    if (incoming.length === 0) {
      levels[nodeId] = 0;
    } else {
      const maxParentLevel = Math.max(...incoming.map(p => calculateLevel(p)));
      levels[nodeId] = maxParentLevel + 1;
    }
    
    return levels[nodeId];
  }
  
  nodes.forEach(n => calculateLevel(n.id));
  
  // Group nodes by level
  const levelGroups: Record<number, GraphNode[]> = {};
  nodes.forEach(n => {
    const level = levels[n.id] || 0;
    if (!levelGroups[level]) levelGroups[level] = [];
    levelGroups[level].push(n);
  });
  
  // Position nodes
  const NODE_WIDTH = 180;
  const NODE_HEIGHT = 80;
  const LEVEL_GAP = 150;
  const NODE_GAP = 30;
  
  const positionedNodes: Node[] = [];
  
  Object.keys(levelGroups).forEach(levelStr => {
    const level = parseInt(levelStr);
    const nodesInLevel = levelGroups[level];
    const totalWidth = nodesInLevel.length * NODE_WIDTH + (nodesInLevel.length - 1) * NODE_GAP;
    const startX = -totalWidth / 2;
    
    nodesInLevel.forEach((node, index) => {
      positionedNodes.push({
        id: node.id,
        type: 'fileNode',
        position: {
          x: startX + index * (NODE_WIDTH + NODE_GAP),
          y: level * LEVEL_GAP,
        },
        data: {
          label: node.label,
          language: node.language,
          lineCount: node.line_count,
          fileType: node.type,
          filePath: node.file_path,
          isSelected: false,
          onClick: () => {},
        },
        sourcePosition: Position.Bottom,
        targetPosition: Position.Top,
      });
    });
  });
  
  // Create edges with styling
  const styledEdges: Edge[] = edges.map((e, index) => ({
  id: `e-${index}`,
  source: e.source,
  target: e.target,
  type: 'smoothstep',
  animated: true,  // Анимация - легче увидеть
  style: { stroke: '#3b82f6', strokeWidth: 2 },  // Синий, толще
  markerEnd: {
    type: MarkerType.ArrowClosed,
    color: '#3b82f6',  // Синий
    width: 20,
    height: 20,
  },
}));
  
  return { nodes: positionedNodes, edges: styledEdges };
}

// ============================================================
// MAIN COMPONENT
// ============================================================

const DependencyGraphPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  
  // State
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [graphData, setGraphData] = useState<DependencyGraphResponse | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterLanguage, setFilterLanguage] = useState<string>('all');
  
  // React Flow state
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  
  // ============================================================
// FETCH DATA
// ============================================================

// Get auth state
const { isAuthenticated, token } = useAuthStore();

useEffect(() => {
  const fetchGraph = async () => {
    // Wait for auth
    if (!projectId || !isAuthenticated || !token) {
      return;
    }
    
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
      
      if (!response.ok) {
        throw new Error(`Failed to fetch: ${response.status}`);
      }
      
      const data: DependencyGraphResponse = await response.json();
      setGraphData(data);
      
      // Calculate layout and set nodes/edges
      const { nodes: layoutNodes, edges: layoutEdges } = calculateLayout(
        data.nodes, 
        data.edges
      );
      
      setNodes(layoutNodes);
      setEdges(layoutEdges);
      
    } catch (err) {
      console.error('Failed to fetch dependency graph:', err);
      setError(err instanceof Error ? err.message : 'Failed to load graph');
    } finally {
      setLoading(false);
    }
  };
  
  fetchGraph();
}, [projectId, isAuthenticated, token, setNodes, setEdges]);
  
  // ============================================================
  // NODE CLICK HANDLER
  // ============================================================
  
  const onNodeClick = useCallback((event: React.MouseEvent, node: Node) => {
    const graphNode = graphData?.nodes.find(n => n.id === node.id);
    setSelectedNode(graphNode || null);
    
    // Update node selection state
    setNodes(nds => 
      nds.map(n => ({
        ...n,
        data: {
          ...n.data,
          isSelected: n.id === node.id,
        },
      }))
    );
  }, [graphData, setNodes]);
  
  // ============================================================
  // FILTER NODES
  // ============================================================
  
  const filteredData = useMemo(() => {
    if (!graphData) return { nodes: [], edges: [] };
    
    let filteredNodes = graphData.nodes;
    
    // Filter by search query
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filteredNodes = filteredNodes.filter(n => 
        n.label.toLowerCase().includes(query) ||
        n.file_path.toLowerCase().includes(query)
      );
    }
    
    // Filter by language
    if (filterLanguage !== 'all') {
      filteredNodes = filteredNodes.filter(n => n.language === filterLanguage);
    }
    
    // Filter edges to only include visible nodes
    const visibleNodeIds = new Set(filteredNodes.map(n => n.id));
    const filteredEdges = graphData.edges.filter(e => 
      visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target)
    );
    
    return { nodes: filteredNodes, edges: filteredEdges };
  }, [graphData, searchQuery, filterLanguage]);
  
  // Update React Flow when filters change
  useEffect(() => {
    if (filteredData.nodes.length > 0) {
      const { nodes: layoutNodes, edges: layoutEdges } = calculateLayout(
        filteredData.nodes,
        filteredData.edges
      );
      setNodes(layoutNodes);
      setEdges(layoutEdges);
    }
  }, [filteredData, setNodes, setEdges]);
  
  // ============================================================
  // GET DEPENDENCIES FOR SELECTED NODE
  // ============================================================
  
  const selectedNodeDeps = useMemo(() => {
    if (!selectedNode || !graphData) return { imports: [], importedBy: [] };
    
    const imports = graphData.edges
      .filter(e => e.source === selectedNode.id)
      .map(e => graphData.nodes.find(n => n.id === e.target))
      .filter(Boolean) as GraphNode[];
    
    const importedBy = graphData.edges
      .filter(e => e.target === selectedNode.id)
      .map(e => graphData.nodes.find(n => n.id === e.source))
      .filter(Boolean) as GraphNode[];
    
    return { imports, importedBy };
  }, [selectedNode, graphData]);
  
  // ============================================================
  // RENDER
  // ============================================================
  
  if (loading) {
    return (
      <div style={{ 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center', 
        height: '100vh',
        backgroundColor: '#f9fafb'
      }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '48px', marginBottom: '16px' }}>📊</div>
          <div style={{ color: '#6b7280' }}>Loading dependency graph...</div>
        </div>
      </div>
    );
  }
  
  if (error) {
    return (
      <div style={{ 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center', 
        height: '100vh',
        backgroundColor: '#fef2f2'
      }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '48px', marginBottom: '16px' }}>❌</div>
          <div style={{ color: '#dc2626', marginBottom: '16px' }}>{error}</div>
          <button
            onClick={() => navigate(-1)}
            style={{
              padding: '8px 16px',
              backgroundColor: '#3b82f6',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer'
            }}
          >
            Go Back
          </button>
        </div>
      </div>
    );
  }
  
  return (
    <div style={{ display: 'flex', height: '100vh', backgroundColor: '#f9fafb' }}>
      {/* Main Graph Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        
        {/* Toolbar */}
        <div style={{
          padding: '12px 20px',
          backgroundColor: 'white',
          borderBottom: '1px solid #e5e7eb',
          display: 'flex',
          alignItems: 'center',
          gap: '16px'
        }}>
          {/* Back button */}
          <button
            onClick={() => navigate(-1)}
            style={{
              padding: '6px 12px',
              backgroundColor: '#f3f4f6',
              border: '1px solid #d1d5db',
              borderRadius: '6px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '4px'
            }}
          >
            ← Back
          </button>
          
          {/* Title */}
          <h1 style={{ 
            fontSize: '18px', 
            fontWeight: 600, 
            color: '#111827',
            margin: 0
          }}>
            📊 {graphData?.project_name} - Dependency Graph
          </h1>
          
          {/* Search */}
          <input
            type="text"
            placeholder="🔍 Search files..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              padding: '8px 12px',
              border: '1px solid #d1d5db',
              borderRadius: '6px',
              width: '200px',
              marginLeft: 'auto'
            }}
          />
          
          {/* Language filter */}
          <select
            value={filterLanguage}
            onChange={(e) => setFilterLanguage(e.target.value)}
            style={{
              padding: '8px 12px',
              border: '1px solid #d1d5db',
              borderRadius: '6px',
              backgroundColor: 'white'
            }}
          >
            <option value="all">All Languages</option>
            {graphData?.stats.languages.map(lang => (
              <option key={lang} value={lang}>
                {LANGUAGE_ICONS[lang] || '📄'} {lang}
              </option>
            ))}
          </select>
          
          {/* Stats */}
          <div style={{ 
            fontSize: '13px', 
            color: '#6b7280',
            display: 'flex',
            gap: '12px'
          }}>
            <span>📁 {filteredData.nodes.length} files</span>
            <span>🔗 {filteredData.edges.length} deps</span>
          </div>
        </div>
        
        {/* React Flow Canvas */}
        <div style={{ flex: 1 }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            nodeTypes={nodeTypes}
            connectionMode={ConnectionMode.Loose}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.1}
            maxZoom={2}
          >
            <Background color="#e5e7eb" gap={20} />
            <Controls />
            <MiniMap 
              nodeColor={(node) => {
                const colors = NODE_COLORS[node.data?.fileType] || NODE_COLORS.file;
                return colors.border;
              }}
              maskColor="rgba(0, 0, 0, 0.1)"
            />
          </ReactFlow>
        </div>
      </div>
      
      {/* Sidebar - File Details */}
      <div style={{
        width: '320px',
        backgroundColor: 'white',
        borderLeft: '1px solid #e5e7eb',
        overflow: 'auto'
      }}>
        {selectedNode ? (
          <div style={{ padding: '20px' }}>
            {/* File Header */}
            <div style={{ marginBottom: '20px' }}>
              <div style={{ 
                fontSize: '24px', 
                marginBottom: '8px' 
              }}>
                {LANGUAGE_ICONS[selectedNode.language] || '📄'}
              </div>
              <h2 style={{ 
                fontSize: '16px', 
                fontWeight: 600, 
                margin: '0 0 4px 0',
                wordBreak: 'break-all'
              }}>
                {selectedNode.label}
              </h2>
              <div style={{ 
                fontSize: '12px', 
                color: '#6b7280',
                wordBreak: 'break-all'
              }}>
                {selectedNode.file_path}
              </div>
            </div>
            
            {/* File Info */}
            <div style={{
              padding: '12px',
              backgroundColor: '#f9fafb',
              borderRadius: '8px',
              marginBottom: '20px'
            }}>
              <div style={{ 
                display: 'grid', 
                gridTemplateColumns: '1fr 1fr',
                gap: '8px',
                fontSize: '13px'
              }}>
                <div>
                  <div style={{ color: '#6b7280' }}>Language</div>
                  <div style={{ fontWeight: 500 }}>{selectedNode.language}</div>
                </div>
                <div>
                  <div style={{ color: '#6b7280' }}>Type</div>
                  <div style={{ fontWeight: 500 }}>{selectedNode.type}</div>
                </div>
                <div>
                  <div style={{ color: '#6b7280' }}>Lines</div>
                  <div style={{ fontWeight: 500 }}>{selectedNode.line_count}</div>
                </div>
                <div>
                  <div style={{ color: '#6b7280' }}>Size</div>
                  <div style={{ fontWeight: 500 }}>
                    {(selectedNode.file_size / 1024).toFixed(1)} KB
                  </div>
                </div>
              </div>
            </div>
            
            {/* Imports (outgoing) */}
            <div style={{ marginBottom: '20px' }}>
              <h3 style={{ 
                fontSize: '14px', 
                fontWeight: 600, 
                marginBottom: '8px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}>
                📥 Imports ({selectedNodeDeps.imports.length})
              </h3>
              {selectedNodeDeps.imports.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {selectedNodeDeps.imports.map(dep => (
                    <div
                      key={dep.id}
                      onClick={() => {
                        setSelectedNode(dep);
                        setNodes(nds => 
                          nds.map(n => ({
                            ...n,
                            data: { ...n.data, isSelected: n.id === dep.id },
                          }))
                        );
                      }}
                      style={{
                        padding: '8px 10px',
                        backgroundColor: '#f3f4f6',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        fontSize: '13px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px'
                      }}
                    >
                      <span>{LANGUAGE_ICONS[dep.language] || '📄'}</span>
                      <span style={{ 
                        overflow: 'hidden', 
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                      }}>
                        {dep.label}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ color: '#9ca3af', fontSize: '13px' }}>
                  No imports
                </div>
              )}
            </div>
            
            {/* Imported By (incoming) */}
            <div>
              <h3 style={{ 
                fontSize: '14px', 
                fontWeight: 600, 
                marginBottom: '8px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}>
                📤 Imported By ({selectedNodeDeps.importedBy.length})
              </h3>
              {selectedNodeDeps.importedBy.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {selectedNodeDeps.importedBy.map(dep => (
                    <div
                      key={dep.id}
                      onClick={() => {
                        setSelectedNode(dep);
                        setNodes(nds => 
                          nds.map(n => ({
                            ...n,
                            data: { ...n.data, isSelected: n.id === dep.id },
                          }))
                        );
                      }}
                      style={{
                        padding: '8px 10px',
                        backgroundColor: '#fef3c7',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        fontSize: '13px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px'
                      }}
                    >
                      <span>{LANGUAGE_ICONS[dep.language] || '📄'}</span>
                      <span style={{ 
                        overflow: 'hidden', 
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                      }}>
                        {dep.label}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ color: '#9ca3af', fontSize: '13px' }}>
                  Not imported by any file
                </div>
              )}
            </div>
            
            {/* Actions */}
            <div style={{ 
              marginTop: '24px', 
              paddingTop: '16px', 
              borderTop: '1px solid #e5e7eb',
              display: 'flex',
              gap: '8px'
            }}>
              <button
                onClick={() => {
                  // Navigate to file in VS Code or Web editor
                  console.log('Open file:', selectedNode.file_path);
                }}
                style={{
                  flex: 1,
                  padding: '8px',
                  backgroundColor: '#3b82f6',
                  color: 'white',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '13px'
                }}
              >
                Open File
              </button>
              <button
                onClick={() => {
                  // Copy path to clipboard
                  navigator.clipboard.writeText(selectedNode.file_path);
                }}
                style={{
                  padding: '8px 12px',
                  backgroundColor: '#f3f4f6',
                  border: '1px solid #d1d5db',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '13px'
                }}
              >
                📋
              </button>
            </div>
          </div>
        ) : (
          <div style={{ 
            padding: '40px 20px', 
            textAlign: 'center',
            color: '#9ca3af'
          }}>
            <div style={{ fontSize: '48px', marginBottom: '12px' }}>👆</div>
            <div>Click a node to see details</div>
          </div>
        )}
        
        {/* Stats Footer */}
        {graphData && (
          <div style={{
            position: 'absolute',
            bottom: 0,
            width: '320px',
            padding: '12px 20px',
            backgroundColor: '#f9fafb',
            borderTop: '1px solid #e5e7eb',
            fontSize: '12px',
            color: '#6b7280'
          }}>
            <div style={{ fontWeight: 600, marginBottom: '4px' }}>
              📊 Project Stats
            </div>
            <div>
              {graphData.stats.total_files} files • {graphData.stats.total_dependencies} dependencies • {graphData.stats.total_lines.toLocaleString()} lines
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default DependencyGraphPage;