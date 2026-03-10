use super::*;

#[test]
fn computes_padded_struct_layout() {
    let layout = struct_layout(&[
        TypeLayout { size: 1, align: 1 },
        TypeLayout { size: 8, align: 8 },
        TypeLayout { size: 1, align: 1 },
    ]);
    assert_eq!(layout.size, 24);
    assert_eq!(layout.align, 8);
}
