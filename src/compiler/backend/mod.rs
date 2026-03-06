pub mod cranelift;
pub mod layout;

use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct BuildArtifact {
    pub executable_path: PathBuf,
    pub object_path: PathBuf,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum BuildOptLevel {
    Default,
    O0,
    O1,
    O2,
    O3,
}

impl BuildOptLevel {
    pub fn cranelift_opt_level(self) -> Option<&'static str> {
        match self {
            Self::Default => None,
            Self::O0 => Some("none"),
            Self::O1 => Some("speed_and_size"),
            Self::O2 => Some("speed"),
            Self::O3 => Some("speed"),
        }
    }
}
