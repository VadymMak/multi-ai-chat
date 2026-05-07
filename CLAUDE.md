# Brain MCP — Always Active

Before answering ANY coding question or making ANY code change, always:

1. Call brain `build_context_for_query` with the user's question to get relevant context
2. Use the returned context to give a better, more informed answer

## Available Brain commands
- Build context: `build context for query "your question"`
- Search files: `search project files for "keyword"`
- Get file: `get file content path/to/file`
- Dependencies: `get file dependencies for path/to/file`

## Why?
Brain has indexed all project files into pgvector and returns only the most relevant 4K tokens instead of reading all files. This saves tokens and improves answer quality.
