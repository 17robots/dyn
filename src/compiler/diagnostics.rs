use std::fmt;
use std::path::PathBuf;

#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum DiagnosticPhase {
    ModuleResolver,
    Lexer,
    Parser,
    Semantic,
    TypeChecker,
    Backend,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum DiagnosticSeverity {
    Error,
    Warning,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum DiagnosticCode {
    E1001,
    E1002,
    E1003,
    E1004,
    E2001,
    E2002,
    E2003,
    E2004,
    E2005,
    E2006,
    E2007,
    E3001,
    E3002,
    E4001,
    E4002,
    E4003,
    E4004,
    E4005,
    E4006,
    E4007,
    E4008,
    E5001,
    E5002,
    E5003,
}

impl DiagnosticCode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::E1001 => "E1001",
            Self::E1002 => "E1002",
            Self::E1003 => "E1003",
            Self::E1004 => "E1004",
            Self::E2001 => "E2001",
            Self::E2002 => "E2002",
            Self::E2003 => "E2003",
            Self::E2004 => "E2004",
            Self::E2005 => "E2005",
            Self::E2006 => "E2006",
            Self::E2007 => "E2007",
            Self::E3001 => "E3001",
            Self::E3002 => "E3002",
            Self::E4001 => "E4001",
            Self::E4002 => "E4002",
            Self::E4003 => "E4003",
            Self::E4004 => "E4004",
            Self::E4005 => "E4005",
            Self::E4006 => "E4006",
            Self::E4007 => "E4007",
            Self::E4008 => "E4008",
            Self::E5001 => "E5001",
            Self::E5002 => "E5002",
            Self::E5003 => "E5003",
        }
    }
}

impl fmt::Display for DiagnosticCode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub struct SourceSpan {
    pub start_byte: usize,
    pub end_byte: usize,
    pub start_line: usize,
    pub start_col: usize,
    pub end_line: usize,
    pub end_col: usize,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DiagnosticLabel {
    pub file_path: PathBuf,
    pub span: Option<SourceSpan>,
    pub message: String,
    pub is_primary: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Diagnostic {
    pub phase: DiagnosticPhase,
    pub severity: DiagnosticSeverity,
    pub code: DiagnosticCode,
    pub message: String,
    pub labels: Vec<DiagnosticLabel>,
    pub notes: Vec<String>,
}

impl Diagnostic {
    pub fn error(phase: DiagnosticPhase, code: DiagnosticCode, message: impl Into<String>) -> Self {
        Self {
            phase,
            severity: DiagnosticSeverity::Error,
            code,
            message: message.into(),
            labels: Vec::new(),
            notes: Vec::new(),
        }
    }

    pub fn with_primary_file_label(
        mut self,
        file_path: PathBuf,
        span: Option<SourceSpan>,
        message: impl Into<String>,
    ) -> Self {
        self.labels.push(DiagnosticLabel {
            file_path,
            span,
            message: message.into(),
            is_primary: true,
        });
        self
    }
}

impl fmt::Display for Diagnostic {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}
