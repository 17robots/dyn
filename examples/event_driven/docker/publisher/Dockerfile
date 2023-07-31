from dyn:slim-alpine as builder
workdir /
copy ./dyn.mod .
copy ./publisher .
run dyn check publisher
run dyn build publisher --release

from scratch
copy --from=builder /build/release/publisher /
cmd /publisher
