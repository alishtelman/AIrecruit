FROM golang:1.23-alpine AS builder

WORKDIR /src
COPY go.mod ./
RUN go mod download
COPY . .
RUN go build -o /out/templates-service ./cmd/templates-service

FROM alpine:3.20

WORKDIR /app
COPY --from=builder /out/templates-service /app/templates-service

EXPOSE 8080
CMD ["/app/templates-service"]
