Source: Test Content/Lab 6 - AST Visitors.pdf

# CSC-223 Lab 6: Implementing AST Visitors for the DEC Language

This programming assignment instructs pairs of students to implement the Visitor design pattern for Abstract Syntax Trees (ASTs) in the DEC language using C#. Students must define a generic IVisitor<TParam, TResult> interface and implement double-dispatch via Accept methods added to AST node classes. The assignment requires building three concrete visitors: UnparseVisitor to reconstruct formatted source code, EvaluateVisitor to interpret program execution with symbol table management and runtime error handling, and NameAnalysisVisitor to perform static analysis verifying variable definitions across scopes using tuple-based context parameters. Comprehensive xUnit testing is required, including both direct visitor unit tests and integration tests that parse complete DEC programs, with final submission via in-person demonstration of code execution.

**Content type:** code

**Keywords:** AST, Visitor pattern, double dispatch, DEC language, static analysis, C#, xUnit testing, symbol table, interpreter

**Key entities:** IVisitor<TParam, TResult>, UnparseVisitor, EvaluateVisitor, NameAnalysisVisitor, Accept method, ExpressionNode, BlockStmt, SymbolTable<string, object>, Parser.Parser.Parse, Tuple<SymbolTable<string, object>, Statement>
