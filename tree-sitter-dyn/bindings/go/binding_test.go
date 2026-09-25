package tree_sitter_dyn_test

import (
	"testing"

	tree_sitter "github.com/tree-sitter/go-tree-sitter"
	tree_sitter_dyn "github.com/17robots/dyn/bindings/go"
)

func TestCanLoadGrammar(t *testing.T) {
	language := tree_sitter.NewLanguage(tree_sitter_dyn.Language())
	if language == nil {
		t.Errorf("Error loading Dyn grammar")
	}
}
