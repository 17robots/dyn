# Workspace dispatcher. Component justfiles own their recipes.
set positional-arguments
set shell := ["bash", "-euo", "pipefail", "-c"]
export BUILD := absolute_path(env('BUILD', 'build'))

all:
    just --justfile compiler/justfile all

release:
    just --justfile compiler/justfile release

smoke:
    just --justfile compiler/justfile smoke

test:
    just --justfile compiler/justfile test

test-c:
    just --justfile compiler/justfile test-c

per-file:
    just --justfile compiler/justfile per-file

perf-compiler:
    just --justfile compiler/justfile perf-compiler

sanitize-test:
    just --justfile compiler/justfile sanitize-test

sanitize-test-c:
    just --justfile compiler/justfile sanitize-test-c

fuzz-c:
    just --justfile compiler/justfile fuzz-c

quality-c:
    just --justfile compiler/justfile quality-c

install:
    just --justfile compiler/justfile install

install-check:
    just --justfile compiler/justfile install-check

package-sdk:
    just --justfile compiler/justfile package-sdk

test-build-plan:
    just --justfile compiler/justfile test-build-plan

test-interface:
    just --justfile compiler/justfile test-interface

test-bind:
    just --justfile compiler/justfile test-bind

test-contracts:
    just --justfile compiler/justfile test-contracts

test-editor:
    just --justfile compiler/justfile test-editor

test-modules:
    just --justfile compiler/justfile test-modules

test-frontend:
    just --justfile compiler/justfile test-frontend

test-static-analysis:
    just --justfile compiler/justfile test-static-analysis

test-libraries:
    just --justfile compiler/justfile test-libraries

test-vendors:
    just --justfile compiler/justfile test-vendors

test-readiness:
    just --justfile compiler/justfile test-readiness

test-followups:
    just --justfile compiler/justfile test-followups

sdk-reference:
    just --justfile compiler/justfile sdk-reference

selfhost-ready:
    just --justfile compiler/justfile selfhost-ready

selfhost-compare:
    just --justfile compiler/justfile selfhost-compare

release-check:
    just --justfile compiler/justfile release-check

vendor-libs:
    just --justfile compiler/justfile vendor-libs

vendor-bindings:
    just --justfile compiler/justfile vendor-bindings

alias compiler := all

artifact +names:
    just --justfile compiler/justfile artifact "$@"

projects: all
    DYN="$BUILD/dyn" BUILD="$BUILD/projects" just --justfile projects/justfile all

test-projects: all
    DYN="$BUILD/dyn" BUILD="$BUILD/projects" just --justfile projects/justfile test

package-projects:
    BUILD="$BUILD/projects" just --justfile projects/justfile package

grammar:
    just --justfile tree-sitter-dyn/justfile generate

test-grammar:
    BUILD="$BUILD/grammar" just --justfile tree-sitter-dyn/justfile check-workspace

grammar-release:
    BUILD="$BUILD/grammar" just --justfile tree-sitter-dyn/justfile release

package-grammar:
    DIST="$BUILD/dist" BUILD="$BUILD/grammar" just --justfile tree-sitter-dyn/justfile package

editor-grammar:
    just --justfile tree-sitter-dyn/justfile editor-grammar

verify-published-grammar:
    just --justfile tree-sitter-dyn/justfile verify-published-grammar

clean: clean-projects clean-grammar clean-compiler

clean-compiler:
    just --justfile compiler/justfile clean

clean-projects:
    BUILD="$BUILD/projects" just --justfile projects/justfile clean

clean-grammar:
    BUILD="$BUILD/grammar" just --justfile tree-sitter-dyn/justfile clean

help:
    @just --list

test-agent-readiness:
    just --justfile compiler/justfile test-agent-readiness

test-preview:
    just --justfile compiler/justfile test-preview
