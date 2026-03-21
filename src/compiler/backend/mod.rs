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
    Os,
    Oz,
}

impl BuildOptLevel {
    pub fn cranelift_opt_level(self) -> Option<&'static str> {
        match self {
            Self::Default => None,
            Self::O0 => Some("none"),
            Self::O1 => Some("speed_and_size"),
            Self::O2 => Some("speed"),
            Self::O3 => Some("speed"),
            Self::Os => Some("speed_and_size"),
            Self::Oz => Some("speed_and_size"),
        }
    }

    pub fn rustc_opt_level(self) -> &'static str {
        match self {
            Self::Default | Self::O2 => "2",
            Self::O0 => "0",
            Self::O1 => "1",
            Self::O3 => "3",
            Self::Os => "s",
            Self::Oz => "z",
        }
    }

    pub fn cc_opt_flag(self) -> &'static str {
        match self {
            Self::Default | Self::O2 => "-O2",
            Self::O0 => "-O0",
            Self::O1 => "-O1",
            Self::O3 => "-O3",
            Self::Os => "-Os",
            Self::Oz => "-Oz",
        }
    }

    pub fn file_suffix(self) -> &'static str {
        match self {
            Self::Default => "Default",
            Self::O0 => "O0",
            Self::O1 => "O1",
            Self::O2 => "O2",
            Self::O3 => "O3",
            Self::Os => "Os",
            Self::Oz => "Oz",
        }
    }
}
