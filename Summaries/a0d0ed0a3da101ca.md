Source: Test Content/Lab 6 - AST Visitors.pdf

# CSC-223 Lab 6: Implementing the Visitor Pattern for AST Traversal

This assignment instructs students to implement the Visitor design pattern for Abstract Syntax Trees (ASTs) in a DEC language parser using C#. Students must define a generic `IVisitor<TParam, TResult>` interface and `Accept` methods across AST node classes to enable double-dispatching, separating traversal logic from node structure. The lab requires implementing three concrete visitors—`UnparseVisitor` for source code reconstruction, `EvaluateVisitor` for program interpretation with symbol table management, and `NameAnalysisVisitor` for static analysis of variable definitions—alongside comprehensive xUnit tests that verify both individual visitor methods and full parsing-to-execution pipelines.

**Content type:** pdf

**Keywords:** Abstract Syntax Tree, Visitor design pattern, double dispatch, DEC language, C#, static analysis, interpreter, symbol table, xUnit testing, name analysis

**Key entities:** IVisitor<TParam, TResult>, UnparseVisitor, EvaluateVisitor, NameAnalysisVisitor, ExpressionNode, BlockStmt, double-dispatching, SymbolTable, CSC-223, DEC language, xUnit, Tuple<SymbolTable<string, object>, Statement>
