using CUE4Parse.UE4.Objects.Core.Math;

static void Near(float actual, float expected)
{
    if (MathF.Abs(actual - expected) > 1e-5f) throw new Exception($"Expected {expected}, got {actual}.");
}
static void NearVector(FVector actual, FVector expected)
{
    Near(actual.X, expected.X); Near(actual.Y, expected.Y); Near(actual.Z, expected.Z);
}
static void NearRotation(FQuat actual, FQuat expected)
{
    var dot = actual.X * expected.X + actual.Y * expected.Y + actual.Z * expected.Z + actual.W * expected.W;
    var lengths = MathF.Sqrt((actual.X * actual.X + actual.Y * actual.Y + actual.Z * actual.Z + actual.W * actual.W) *
                            (expected.X * expected.X + expected.Y * expected.Y + expected.Z * expected.Z + expected.W * expected.W));
    Near(MathF.Abs(dot / lengths), 1);
}
static FQuat Rotate(float x, float y, float z, float angle)
{
    var half = angle / 2;
    return new FQuat(x * MathF.Sin(half), y * MathF.Sin(half), z * MathF.Sin(half), MathF.Cos(half));
}

var parents = new[] { -1, 0 };
var bind = new[] {
    new FTransform(Rotate(1, 0, 0, 0.3f), new FVector(10, 0, 0), new FVector(2, 2, 2)),
    new FTransform(Rotate(0, 1, 0, 0.4f), new FVector(0, 10, 0), FVector.OneVector),
};
var basePose = new[] {
    new FTransform(Rotate(0, 1, 0, 0.7f), new FVector(3, 4, 5), FVector.OneVector),
    new FTransform(Rotate(1, 0, 0, 0.9f), new FVector(6, 7, 8), new FVector(3, 3, 3)),
};
var deltas = new[] { Rotate(0, 0, 1, 0.5f), Rotate(1, 0, 0, 0.6f) };
foreach (var meshSpace in new[] { false, true })
{
    var posed = new FTransform[2];
    var globalBind = new FQuat[2];
    var globalPosed = new FQuat[2];
    for (var bone = 0; bone < 2; bone++)
    {
        globalBind[bone] = bone == 0 || !meshSpace ? bind[bone].Rotation : globalBind[0] * bind[bone].Rotation;
        globalPosed[bone] = deltas[bone] * globalBind[bone];
        var local = bone == 0 || !meshSpace ? globalPosed[bone] : globalPosed[0].Inverse() * globalPosed[bone];
        posed[bone] = new FTransform(local, bind[bone].Translation + new FVector(1, 2, 3), bind[bone].Scale3D * 1.5f);
    }
    var actual = GenericAnimationDecoder.RebasePose(bind, posed, basePose, parents, meshSpace);
    for (var bone = 0; bone < 2; bone++)
    {
        var actualRotation = meshSpace && bone > 0 ? actual[0].Rotation * actual[bone].Rotation : actual[bone].Rotation;
        var baseRotation = meshSpace && bone > 0 ? basePose[0].Rotation * basePose[bone].Rotation : basePose[bone].Rotation;
        NearRotation(actualRotation, deltas[bone] * baseRotation);
        NearVector(actual[bone].Translation, basePose[bone].Translation + new FVector(1, 2, 3));
        NearVector(actual[bone].Scale3D, basePose[bone].Scale3D * 1.5f);
    }
}
try
{
    bind[0].Scale3D = FVector.ZeroVector;
    GenericAnimationDecoder.RebasePose(bind, basePose, basePose, parents, false);
    throw new Exception("Zero bind scale was accepted.");
}
catch (NotSupportedException) { }
Console.WriteLine("GENERIC_ADDITIVE_POSE_OK: local and mesh-space rotations, translations, scales, zero-scale guard");
