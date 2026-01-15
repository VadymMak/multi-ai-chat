/**
 * Route Configuration & Navigation Components
 * 
 * Add these to your existing router setup
 */

// ============================================================
// 1. ADD TO YOUR ROUTER (e.g., App.tsx or routes.tsx)
// ============================================================

/*
import DependencyGraphPage from './pages/DependencyGraphPage';

// In your Routes:
<Route path="/project/:projectId/graph" element={<DependencyGraphPage />} />
*/

// ============================================================
// 2. BUTTON COMPONENT TO OPEN GRAPH
// ============================================================

import React from 'react';
import { useNavigate } from 'react-router-dom';

interface ViewGraphButtonProps {
  projectId: number;
  variant?: 'button' | 'icon' | 'link';
  className?: string;
}

export const ViewGraphButton: React.FC<ViewGraphButtonProps> = ({
  projectId,
  variant = 'button',
  className = ''
}) => {
  const navigate = useNavigate();
  
  const handleClick = () => {
    navigate(`/project/${projectId}/graph`);
  };
  
  if (variant === 'icon') {
    return (
      <button
        onClick={handleClick}
        title="View Dependency Graph"
        className={className}
        style={{
          padding: '8px',
          backgroundColor: 'transparent',
          border: '1px solid #d1d5db',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '18px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center'
        }}
      >
        📊
      </button>
    );
  }
  
  if (variant === 'link') {
    return (
      <a
        onClick={handleClick}
        className={className}
        style={{
          color: '#3b82f6',
          cursor: 'pointer',
          textDecoration: 'underline',
          fontSize: '14px'
        }}
      >
        View Dependency Graph →
      </a>
    );
  }
  
  // Default: full button
  return (
    <button
      onClick={handleClick}
      className={className}
      style={{
        padding: '10px 16px',
        backgroundColor: '#3b82f6',
        color: 'white',
        border: 'none',
        borderRadius: '8px',
        cursor: 'pointer',
        fontSize: '14px',
        fontWeight: 500,
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        transition: 'background-color 0.2s'
      }}
      onMouseOver={(e) => e.currentTarget.style.backgroundColor = '#2563eb'}
      onMouseOut={(e) => e.currentTarget.style.backgroundColor = '#3b82f6'}
    >
      📊 View Dependency Graph
    </button>
  );
};

// ============================================================
// 3. PROJECT CARD EXAMPLE (shows how to integrate button)
// ============================================================

interface ProjectCardProps {
  project: {
    id: number;
    name: string;
    description?: string;
    files_count?: number;
    indexed_at?: string;
  };
}

export const ProjectCardWithGraph: React.FC<ProjectCardProps> = ({ project }) => {
  const navigate = useNavigate();
  
  return (
    <div style={{
      padding: '20px',
      backgroundColor: 'white',
      borderRadius: '12px',
      border: '1px solid #e5e7eb',
      boxShadow: '0 1px 3px rgba(0,0,0,0.1)'
    }}>
      {/* Header */}
      <div style={{ 
        display: 'flex', 
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        marginBottom: '12px'
      }}>
        <div>
          <h3 style={{ margin: '0 0 4px 0', fontSize: '18px' }}>
            {project.name}
          </h3>
          {project.description && (
            <p style={{ margin: 0, color: '#6b7280', fontSize: '14px' }}>
              {project.description}
            </p>
          )}
        </div>
        <ViewGraphButton projectId={project.id} variant="icon" />
      </div>
      
      {/* Stats */}
      <div style={{
        display: 'flex',
        gap: '16px',
        fontSize: '13px',
        color: '#6b7280',
        marginBottom: '16px'
      }}>
        {project.files_count && (
          <span>📁 {project.files_count} files</span>
        )}
        {project.indexed_at && (
          <span>🕐 Indexed {new Date(project.indexed_at).toLocaleDateString()}</span>
        )}
      </div>
      
      {/* Actions */}
      <div style={{ display: 'flex', gap: '8px' }}>
        <button
          onClick={() => navigate(`/project/${project.id}`)}
          style={{
            flex: 1,
            padding: '10px',
            backgroundColor: '#f3f4f6',
            border: '1px solid #d1d5db',
            borderRadius: '6px',
            cursor: 'pointer'
          }}
        >
          Open Project
        </button>
        <ViewGraphButton projectId={project.id} />
      </div>
    </div>
  );
};

// ============================================================
// 4. INSTALL DEPENDENCIES
// ============================================================

/*
Run in your frontend directory:

npm install reactflow
# or
yarn add reactflow

The package includes:
- ReactFlow component
- Controls (zoom buttons)
- MiniMap
- Background
- All necessary types for TypeScript
*/

// ============================================================
// 5. FILE STRUCTURE
// ============================================================

/*
frontend/src/
├── pages/
│   └── DependencyGraphPage.tsx    ← Main page (created above)
├── components/
│   └── graph/
│       └── ViewGraphButton.tsx    ← This file
├── hooks/
│   └── useDependencyGraph.ts      ← Hook (created above)
└── App.tsx                        ← Add route here
*/

export default ViewGraphButton;