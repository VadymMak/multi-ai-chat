# File: backend/app/services/dependency_graph.py
"""
Dependency Graph Service - Topological Sort for File Generation Order

This service analyzes file dependencies and determines the correct
order for generating files so that dependencies are generated first.
"""

from typing import List, Dict, Set, Tuple
from collections import defaultdict, deque
import logging

logger = logging.getLogger(__name__)


class DependencyGraph:
    """
    Build and analyze dependency graph for file generation order
    """
    
    def __init__(self):
        self.graph: Dict[str, List[str]] = defaultdict(list)  # file -> [dependencies]
        self.reverse_graph: Dict[str, List[str]] = defaultdict(list)  # file -> [dependents]
        self.all_files: Set[str] = set()
        self.in_degree: Dict[str, int] = defaultdict(int)
    
    def add_file(self, file_path: str):
        """Register a file in the graph"""
        self.all_files.add(file_path)
        if file_path not in self.in_degree:
            self.in_degree[file_path] = 0
    
    def add_dependency(self, source_file: str, target_file: str):
        """
        Add dependency: source_file depends on target_file
        
        Example: 
            logger.ts depends on types.d.ts
            add_dependency('logger.ts', 'types.d.ts')
            
        Meaning: types.d.ts must be generated BEFORE logger.ts
        """
        self.add_file(source_file)
        self.add_file(target_file)
        
        # Build forward graph (who depends on whom)
        self.graph[source_file].append(target_file)
        
        # Build reverse graph (who is dependent on me)
        self.reverse_graph[target_file].append(source_file)
        
        # Increase in-degree (number of dependencies)
        self.in_degree[source_file] += 1
    
    def get_generation_order(self) -> List[str]:
        """
        Get files in correct generation order using Topological Sort
        
        Algorithm: Kahn's Algorithm
        1. Start with files that have no dependencies (in_degree = 0)
        2. Generate those first
        3. Remove them from graph
        4. Repeat until all files processed
        
        Returns:
            List of file paths in generation order
            
        Raises:
            ValueError: If circular dependencies detected
        """
        
        # Copy in_degree to avoid modifying original
        in_degree = self.in_degree.copy()
        
        # Find files with no dependencies (in_degree = 0)
        queue = deque([
            file for file in self.all_files 
            if in_degree[file] == 0
        ])
        
        generation_order = []
        
        while queue:
            # Take a file with no dependencies
            current_file = queue.popleft()
            generation_order.append(current_file)
            
            # For all files that depend on current_file
            for dependent in self.reverse_graph[current_file]:
                # Reduce their in-degree (one dependency satisfied)
                in_degree[dependent] -= 1
                
                # If all dependencies satisfied, add to queue
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        
        # Check for circular dependencies
        if len(generation_order) != len(self.all_files):
            missing_files = self.all_files - set(generation_order)
            raise ValueError(
                f"Circular dependencies detected! "
                f"Cannot generate files: {missing_files}"
            )
        
        logger.info(f"📊 Generation order determined: {len(generation_order)} files")
        return generation_order
    
    def get_dependency_depth(self, file_path: str) -> int:
        """
        Get dependency depth (how many levels of dependencies)
        
        Example:
            types.d.ts: depth 0 (no dependencies)
            logger.ts: depth 1 (depends on types.d.ts)
            controller.ts: depth 2 (depends on logger.ts which depends on types.d.ts)
        """
        if file_path not in self.all_files:
            return -1
        
        visited = set()
        
        def dfs(node: str) -> int:
            if node in visited:
                return 0
            visited.add(node)
            
            if not self.graph[node]:
                return 0
            
            max_depth = 0
            for dep in self.graph[node]:
                max_depth = max(max_depth, dfs(dep) + 1)
            
            return max_depth
        
        return dfs(file_path)
    
    def get_immediate_dependencies(self, file_path: str) -> List[str]:
        """Get direct dependencies of a file"""
        return self.graph.get(file_path, [])
    
    def get_all_dependencies(self, file_path: str) -> Set[str]:
        """Get all dependencies (direct + transitive)"""
        if file_path not in self.all_files:
            return set()
        
        visited = set()
        
        def dfs(node: str):
            if node in visited:
                return
            visited.add(node)
            
            for dep in self.graph[node]:
                dfs(dep)
        
        dfs(file_path)
        visited.remove(file_path)  # Don't include self
        return visited
    
    def detect_circular_dependencies(self) -> List[List[str]]:
        """
        Detect circular dependencies in the graph
        
        Returns:
            List of cycles, each cycle is a list of file paths
        """
        visited = set()
        rec_stack = set()
        cycles = []
        
        def dfs(node: str, path: List[str]) -> bool:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in self.graph[node]:
                if neighbor not in visited:
                    if dfs(neighbor, path.copy()):
                        return True
                elif neighbor in rec_stack:
                    # Cycle found!
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(cycle)
                    return True
            
            rec_stack.remove(node)
            return False
        
        for file in self.all_files:
            if file not in visited:
                dfs(file, [])
        
        return cycles


def build_dependency_graph(
    files: List[str],
    dependencies: List[Tuple[str, str]]
) -> DependencyGraph:
    """
    Build dependency graph from file list and dependencies
    
    Args:
        files: List of file paths
        dependencies: List of (source_file, target_file) tuples
        
    Returns:
        DependencyGraph instance
    """
    graph = DependencyGraph()
    
    # Add all files
    for file_path in files:
        graph.add_file(file_path)
    
    # Add all dependencies
    for source, target in dependencies:
        graph.add_dependency(source, target)
    
    logger.info(f"📊 Built dependency graph: {len(files)} files, {len(dependencies)} dependencies")
    
    return graph


def get_generation_order_from_db(
    project_id: int,
    db  # SQLAlchemy Session
) -> List[str]:
    """
    Load files and dependencies from database, return generation order
    
    Args:
        project_id: Project ID
        db: Database session
        
    Returns:
        List of file paths in correct generation order
    """
    from sqlalchemy import text
    
    # Load all files
    files_result = db.execute(text("""
        SELECT file_path
        FROM file_specifications
        WHERE project_id = :project_id
        ORDER BY file_number
    """), {"project_id": project_id}).fetchall()
    
    files = [row[0] for row in files_result]
    
    # Load all dependencies
    deps_result = db.execute(text("""
        SELECT source_file, target_file
        FROM file_dependencies
        WHERE project_id = :project_id
    """), {"project_id": project_id}).fetchall()
    
    dependencies = [(row[0], row[1]) for row in deps_result]
    
    logger.info(f"📊 Loaded {len(files)} files, {len(dependencies)} dependencies from DB")
    
    # Build graph and get order
    graph = build_dependency_graph(files, dependencies)
    
    # Check for circular dependencies
    cycles = graph.detect_circular_dependencies()
    if cycles:
        logger.warning(f"⚠️ Circular dependencies detected: {cycles}")
        # Don't raise error, just log warning
        # Generation will still work, just might have some import issues
    
    return graph.get_generation_order()


if __name__ == "__main__":
    # Example usage / testing
    print("=== Dependency Graph Example ===\n")
    
    # Create a simple graph
    graph = DependencyGraph()
    
    # Add files
    files = [
        "types.d.ts",
        "logger.ts",
        "helpers.ts",
        "auth.ts",
        "controller.ts",
        "index.ts"
    ]
    
    for f in files:
        graph.add_file(f)
    
    # Add dependencies
    graph.add_dependency("logger.ts", "types.d.ts")
    graph.add_dependency("helpers.ts", "types.d.ts")
    graph.add_dependency("auth.ts", "types.d.ts")
    graph.add_dependency("auth.ts", "logger.ts")
    graph.add_dependency("controller.ts", "auth.ts")
    graph.add_dependency("controller.ts", "helpers.ts")
    graph.add_dependency("index.ts", "controller.ts")
    graph.add_dependency("index.ts", "logger.ts")
    
    # Get generation order
    order = graph.get_generation_order()
    
    print("Generation Order:")
    for i, file in enumerate(order, 1):
        depth = graph.get_dependency_depth(file)
        deps = graph.get_immediate_dependencies(file)
        print(f"{i}. {file} (depth: {depth}, depends on: {deps})")
    
    print("\nExpected order:")
    print("1. types.d.ts (no dependencies)")
    print("2-3. logger.ts, helpers.ts (depend on types)")
    print("4. auth.ts (depends on types + logger)")
    print("5. controller.ts (depends on auth + helpers)")
    print("6. index.ts (depends on controller + logger)")