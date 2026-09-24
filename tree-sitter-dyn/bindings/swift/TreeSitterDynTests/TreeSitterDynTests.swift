import XCTest
import SwiftTreeSitter
import TreeSitterDyn

final class TreeSitterDynTests: XCTestCase {
    func testCanLoadGrammar() throws {
        let parser = Parser()
        let language = Language(language: tree_sitter_dyn())
        XCTAssertNoThrow(try parser.setLanguage(language),
                         "Error loading Dyn grammar")
    }
}
